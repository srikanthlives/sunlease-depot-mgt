"""Trip sheets (Part 2): entered by MIS clerks from the paper sheet, approved by a publisher."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.access import Scope, scope
from app.db.session import get_db
from app.models.enums import CrewRole, Role, RowStatus, TripSheetStatus
from app.models.models import BusSchedule, SheetScan, SheetScanPage, TripReason, TripSheet, TripSheetCrew, TripSheetRow
from app.schemas import schemas as S
from app.services import audit_service, scan_intake, settings_service
from app.services import trip_sheet_service as ts

router = APIRouter(prefix="/api", tags=["trip-sheets"])


def _t(t):
    return t.strftime("%H:%M") if t else None


def _get_sheet(db: Session, sc: Scope, sheet_id: int, minimum=Role.VIEWER) -> TripSheet:
    s = db.get(TripSheet, sheet_id)
    if not s:
        raise HTTPException(404, "Trip sheet not found")
    sc.require(s.cost_center_id, minimum, "Trip sheet")
    return s


def _sheet_brief(s: TripSheet) -> dict:
    return {"sheet_id": s.sheet_id, "cost_center_id": s.cost_center_id, "schedule_id": s.schedule_id,
            "schedule_code": s.schedule.schedule_code, "schedule_version_id": s.schedule_version_id,
            "version_number": s.version.version_number, "vehicle_id": s.vehicle_id,
            "fleet_number": s.vehicle.fleet_number, "operating_date": s.operating_date, "status": s.status,
            "paper_sheet_no": s.paper_sheet_no,
            "bus_change_fleet_number": s.bus_change_vehicle.fleet_number if s.bus_change_vehicle else s.bus_change_registration}


def _sheet_out(db: Session, s: TripSheet) -> dict:
    cfg = settings_service.get_all(db, s.cost_center_id)
    summary, billing = ts.summarize_sheet(s, cfg)
    minutes = summary["crew_minutes"]
    v = s.version
    rows = []
    for r in sorted(s.rows, key=lambda x: x.row_sequence):
        rows.append({
            "row_id": r.row_id, "row_sequence": r.row_sequence, "status": r.status, "is_extra": r.activity_id is None,
            "planned": ts.activity_planned(r.activity),
            "actual_start_day_offset": r.actual_start_day_offset, "actual_start_time": _t(r.actual_start_time),
            "actual_end_day_offset": r.actual_end_day_offset, "actual_end_time": _t(r.actual_end_time),
            "start_odometer_km": r.start_odometer_km, "end_odometer_km": r.end_odometer_km,
            "start_soc_pct": r.start_soc_pct, "end_soc_pct": r.end_soc_pct, "energy_kwh": r.energy_kwh,
            "stopped_at_route_stop_id": r.stopped_at_route_stop_id, "reason_id": r.reason_id,
            "attributable_to": r.attributable_to, "remarks": r.remarks,
            "extra_from_location_id": r.extra_from_location_id, "extra_to_location_id": r.extra_to_location_id,
            "extra_payable": r.extra_payable,
            "stops": [{"scheduled_stop_time_id": st.scheduled_stop_time_id, "stop_sequence": st.stop_sequence,
                       "arrival_day_offset": st.arrival_day_offset, "arrival_time": _t(st.arrival_time),
                       "departure_day_offset": st.departure_day_offset, "departure_time": _t(st.departure_time),
                       "odometer_km": st.odometer_km, "soc_pct": st.soc_pct} for st in r.stops],
            "billing": billing[r.row_id],
        })
    crew = [{"crew_id": c.crew_id, "crew_role": c.crew_role, "shift_id": c.shift_id,
             "shift_name": c.shift.shift_name if c.shift else None, "employee_id": c.employee_id,
             "employee_name": c.employee.full_name if c.employee else None,
             "employee_number": c.employee.employee_number if c.employee else None,
             "duty_start_day_offset": c.duty_start_day_offset, "duty_start_time": _t(c.duty_start_time),
             "duty_end_day_offset": c.duty_end_day_offset, "duty_end_time": _t(c.duty_end_time),
             "replaces_crew_id": c.replaces_crew_id, "handover_reason": c.handover_reason,
             "working_minutes": minutes.get(c.crew_id)} for c in s.crew]
    closing = ts.previous_closing(db, s)
    return {**_sheet_brief(s), "remarks": s.remarks, "schedule_name": s.schedule.schedule_name,
            "paper_version_number": s.paper_version_number,
            "bus_change_registration": s.bus_change_registration, "bus_change_vehicle_id": s.bus_change_vehicle_id,
            "bus_change_from_row_id": s.bus_change_from_row_id, "bus_change_reason_id": s.bus_change_reason_id,
            "previous_closing": closing,
            "registration_number": s.vehicle.registration_number,
            "crew_mode": v.crew_mode, "conductor_required": v.conductor_required,
            "submitted_at": s.submitted_at, "approved_at": s.approved_at,
            "billing_rule": {"bill_lost_km_attributable_to": cfg["bill_lost_km_attributable_to"],
                             "odometer_tolerance_pct": cfg["odometer_tolerance_pct"]},
            # what the duty roster has for this bus and date, so the entry screen can say
            # when the sheet's crew disagrees with it
            "roster_crew": ts.roster_crew_check(db, s),
            "rows": rows, "crew": crew, "summary": summary}


# ---------------- board / list ----------------
@router.get("/trip-sheets/board")
def board(date: dt.date, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """Every schedule with a published version on `date`, with its trip sheet status."""
    schedules = sc.filter(db.query(BusSchedule), BusSchedule.cost_center_id).order_by(BusSchedule.schedule_code).all()
    return ts.board(db, schedules, date)


@router.get("/trip-sheets")
def list_sheets(date_from: dt.date | None = None, date_to: dt.date | None = None, status: str | None = None,
                schedule_id: int | None = None, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    q = sc.filter(db.query(TripSheet), TripSheet.cost_center_id)
    if date_from:
        q = q.filter(TripSheet.operating_date >= date_from)
    if date_to:
        q = q.filter(TripSheet.operating_date <= date_to)
    if status:
        q = q.filter(TripSheet.status == status)
    if schedule_id:
        q = q.filter(TripSheet.schedule_id == schedule_id)
    return [_sheet_brief(s) for s in q.order_by(TripSheet.operating_date.desc(), TripSheet.sheet_id).limit(500).all()]


@router.post("/trip-sheets", status_code=201)
def create_sheet(body: S.TripSheetCreate, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    sched = db.get(BusSchedule, body.schedule_id)
    if not sched:
        raise HTTPException(404, "Schedule not found")
    sc.require(sched.cost_center_id, Role.MIS, "Schedule")
    try:
        sheet = ts.create_sheet(db, sched, body.operating_date, sc.user)
    except HTTPException:
        db.rollback()
        raise
    audit_service.record(db, sc.user, "CREATE", "TripSheet", sheet.sheet_id,
                         {"schedule": sched.schedule_code, "date": body.operating_date.isoformat()})
    db.commit()
    db.refresh(sheet)
    return _sheet_out(db, sheet)


@router.get("/trip-sheets/{sheet_id}")
def get_sheet(sheet_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    return _sheet_out(db, _get_sheet(db, sc, sheet_id))


@router.put("/trip-sheets/{sheet_id}")
def save_sheet(sheet_id: int, body: S.TripSheetSave, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """Save the header, row actuals and crew duties in one go (the Ctrl+S of the entry screen)."""
    s = _get_sheet(db, sc, sheet_id, Role.MIS)
    ts.assert_editable(s)
    rows = {r.row_id: r for r in s.rows}
    crew = {c.crew_id: c for c in s.crew}
    try:
        s.paper_sheet_no, s.remarks, s.paper_version_number = body.paper_sheet_no, body.remarks, body.paper_version_number
        ts.apply_bus_change(db, s, body.bus_change_registration, body.bus_change_from_row_id, body.bus_change_reason_id)
        for data in body.rows:
            if data.row_id not in rows:
                raise HTTPException(422, f"Row {data.row_id} is not on this sheet")
            ts.apply_row(db, s, rows[data.row_id], data)
        for data in body.crew:
            if data.crew_id not in crew:
                raise HTTPException(422, f"Crew entry {data.crew_id} is not on this sheet")
            ts.apply_crew(db, s, crew[data.crew_id], data)
        ts.validate_sheet(db, s)        # refreshes the warning / error counts the board shows
        audit_service.record(db, sc.user, "UPDATE", "TripSheet", sheet_id,
                             {"rows": len(body.rows), "crew": len(body.crew)})
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    db.refresh(s)
    return _sheet_out(db, s)


@router.delete("/trip-sheets/{sheet_id}", status_code=204)
def delete_sheet(sheet_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    s = _get_sheet(db, sc, sheet_id, Role.MIS)
    ts.assert_editable(s)
    audit_service.record(db, sc.user, "DELETE", "TripSheet", sheet_id,
                         {"schedule": s.schedule.schedule_code, "date": s.operating_date.isoformat()})
    db.delete(s)
    db.commit()


# ---------------- extra runs / crew ----------------
@router.post("/trip-sheets/{sheet_id}/extra-rows", status_code=201)
def add_extra_row(sheet_id: int, after_row_id: int | None = None, db: Session = Depends(get_db),
                  sc: Scope = Depends(scope)):
    """An unplanned run (e.g. a breakdown tow or a workshop trip), placed after `after_row_id`."""
    s = _get_sheet(db, sc, sheet_id, Role.MIS)
    ts.assert_editable(s)
    ordered = sorted(s.rows, key=lambda r: r.row_sequence)
    idx = next((i + 1 for i, r in enumerate(ordered) if r.row_id == after_row_id), len(ordered))
    new = TripSheetRow(sheet_id=s.sheet_id, activity_id=None, status=RowStatus.OPERATED)
    ordered.insert(idx, new)
    for i, r in enumerate(ordered, start=1):   # renumber 10, 20, 30 ...
        r.row_sequence = i * 10
    db.add(new)
    audit_service.record(db, sc.user, "CREATE", "TripSheetRow", sheet_id, {"extra_after": after_row_id})
    db.commit()
    db.refresh(s)
    return _sheet_out(db, s)


@router.delete("/trip-sheet-rows/{row_id}")
def delete_extra_row(row_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    r = db.get(TripSheetRow, row_id)
    if not r:
        raise HTTPException(404, "Row not found")
    s = _get_sheet(db, sc, r.sheet_id, Role.MIS)
    ts.assert_editable(s)
    if r.activity_id is not None:
        raise HTTPException(409, "Planned rows cannot be removed - mark them cancelled instead")
    audit_service.record(db, sc.user, "DELETE", "TripSheetRow", row_id, {"sheet": s.sheet_id})
    if s.bus_change_from_row_id == row_id:
        s.bus_change_from_row_id = None
    db.delete(r)
    db.commit()
    db.refresh(s)
    return _sheet_out(db, s)


@router.post("/trip-sheets/{sheet_id}/crew", status_code=201)
def add_crew(sheet_id: int, body: S.CrewAddIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    s = _get_sheet(db, sc, sheet_id, Role.MIS)
    ts.assert_editable(s)
    db.add(TripSheetCrew(sheet_id=s.sheet_id, crew_role=body.crew_role))
    audit_service.record(db, sc.user, "CREATE", "TripSheetCrew", sheet_id, body.model_dump())
    db.commit()
    db.refresh(s)
    return _sheet_out(db, s)


def _get_crew(db: Session, sc: Scope, crew_id: int) -> tuple[TripSheetCrew, TripSheet]:
    c = db.get(TripSheetCrew, crew_id)
    if not c:
        raise HTTPException(404, "Crew entry not found")
    s = _get_sheet(db, sc, c.sheet_id, Role.MIS)
    ts.assert_editable(s)
    return c, s


@router.delete("/trip-sheet-crew/{crew_id}")
def delete_crew(crew_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    c, s = _get_crew(db, sc, crew_id)
    for other in s.crew:            # a later duty that took over from this one becomes stand-alone
        if other.replaces_crew_id == crew_id:
            other.replaces_crew_id = None
    audit_service.record(db, sc.user, "DELETE", "TripSheetCrew", crew_id, {"sheet": s.sheet_id})
    db.delete(c)
    db.commit()
    db.refresh(s)
    return _sheet_out(db, s)


@router.post("/trip-sheet-crew/{crew_id}/handover")
def crew_handover(crew_id: int, body: S.HandoverIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """The crew member leaves mid-duty: their duty ends at the change time and the replacement's starts."""
    c, s = _get_crew(db, sc, crew_id)
    try:
        new = ts.handover(db, s, c, body)
    except HTTPException:
        db.rollback()
        raise
    audit_service.record(db, sc.user, "HANDOVER", "TripSheetCrew", crew_id,
                         {"new_crew": new.crew_id, "at": f"+{body.at_day_offset} {body.at_time}", "reason": body.reason})
    db.commit()
    db.refresh(s)
    return _sheet_out(db, s)


# ---------------- workflow ----------------
@router.post("/trip-sheets/{sheet_id}/validate")
def validate(sheet_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    return ts.validate_sheet(db, _get_sheet(db, sc, sheet_id))


@router.post("/trip-sheets/{sheet_id}/submit")
def submit(sheet_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    s = _get_sheet(db, sc, sheet_id, Role.MIS)
    ts.assert_editable(s)
    result = ts.validate_sheet(db, s)
    if not result["valid"]:
        raise HTTPException(422, {"message": "Trip sheet has errors", "issues": result["issues"]})
    s.status, s.submitted_by, s.submitted_at = TripSheetStatus.SUBMITTED, sc.user.id, dt.datetime.utcnow()
    audit_service.record(db, sc.user, "SUBMIT", "TripSheet", sheet_id, {"billable_km": result["summary"]["billable_km"]})
    db.commit()
    return _sheet_out(db, s)


@router.post("/trip-sheets/{sheet_id}/approve")
def approve(sheet_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    s = _get_sheet(db, sc, sheet_id, Role.PUBLISHER)
    if s.status != TripSheetStatus.SUBMITTED:
        raise HTTPException(409, "Only a submitted trip sheet can be approved")
    result = ts.validate_sheet(db, s)
    if not result["valid"]:
        raise HTTPException(422, {"message": "Trip sheet has errors", "issues": result["issues"]})
    s.status, s.approved_by, s.approved_at = TripSheetStatus.APPROVED, sc.user.id, dt.datetime.utcnow()
    audit_service.record(db, sc.user, "APPROVE", "TripSheet", sheet_id, {"billable_km": result["summary"]["billable_km"]})
    db.commit()
    return _sheet_out(db, s)


@router.post("/trip-sheets/{sheet_id}/return")
def return_to_draft(sheet_id: int, body: S.ReopenIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """Send a submitted sheet back to the clerk (publisher), or reopen an approved one (admin only)."""
    s = _get_sheet(db, sc, sheet_id, Role.PUBLISHER)
    if s.status == TripSheetStatus.APPROVED and sc.rank(s.cost_center_id) < Role.RANK[Role.ADMIN]:
        raise HTTPException(403, "Only an admin can reopen an approved trip sheet")
    if s.status == TripSheetStatus.DRAFT:
        raise HTTPException(409, "The trip sheet is already a draft")
    action = "REOPEN" if s.status == TripSheetStatus.APPROVED else "RETURN"
    s.status, s.approved_by, s.approved_at = TripSheetStatus.DRAFT, None, None
    audit_service.record(db, sc.user, action, "TripSheet", sheet_id, {"reason": body.reason})
    db.commit()
    return _sheet_out(db, s)


@router.get("/trip-sheets/{sheet_id}/scan")
def sheet_scan(sheet_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """The scanned paper this sheet was read from: every page of it, and what could not be made out.

    A long day runs over more than one page, so all the pages of the upload that filled this sheet
    come back, newest upload first - they are what the entry screen shows as the attached paper.
    """
    s = _get_sheet(db, sc, sheet_id)
    pages = (db.query(SheetScanPage).filter(SheetScanPage.sheet_id == sheet_id)
             .order_by(SheetScanPage.scan_id.desc(), SheetScanPage.page_no).all())
    if not pages:
        return {"from_scan": False, "pages": [], "issues": [], "fields_read": 0, "fields_unsure": 0}
    newest = pages[0].scan_id
    pages = [p for p in pages if p.scan_id == newest]        # older uploads were replaced
    out = [scan_intake.page_out(p) for p in pages]
    scan = db.get(SheetScan, newest)
    # only what the paper could not tell us: validation findings are shown by the validate panel
    reading = [x for p in out for x in p["issues"]
               if x.get("field") or x["code"] in ("ROW_NOT_READ", "STATUS_UNSURE")]
    return {"from_scan": True, "scan_id": newest, "file_name": scan.file_name if scan else None,
            "uploaded_at": scan.created_at if scan else None,
            "fields_read": sum(p["fields_read"] for p in out),
            "fields_unsure": sum(p["fields_unsure"] for p in out),
            "pages": [{"page_no": p["page_no"], "status": p["status"], "fields_read": p["fields_read"],
                       "fields_unsure": p["fields_unsure"],
                       "image_url": f"/api/trip-sheets/scans/{newest}/pages/{p['page_no']}/image"} for p in out],
            "issues": reading}


# ---------------- reasons (per company) ----------------
def _reason_out(r: TripReason) -> dict:
    return {"reason_id": r.reason_id, "company_id": r.company_id, "reason_code": r.reason_code,
            "reason_name": r.reason_name, "reason_name_local": r.reason_name_local,
            "default_attributable_to": r.default_attributable_to, "is_active": r.is_active}


@router.get("/trip-reasons")
def list_reasons(db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    for company in sc.visible_companies:
        ts.ensure_reasons(db, company)
    db.commit()
    q = db.query(TripReason).filter(TripReason.company_id.in_(sc.visible_companies))
    return [_reason_out(r) for r in q.order_by(TripReason.company_id, TripReason.reason_code).all()]


@router.post("/trip-reasons", status_code=201)
def create_reason(body: S.TripReasonIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    company = sc.target_company(Role.SCHEDULER)
    if db.query(TripReason).filter_by(company_id=company, reason_code=body.reason_code).first():
        raise HTTPException(409, f"Reason code {body.reason_code} already exists")
    r = TripReason(company_id=company, **body.model_dump())
    db.add(r)
    db.flush()
    audit_service.record(db, sc.user, "CREATE", "TripReason", r.reason_id, body.model_dump())
    db.commit()
    return _reason_out(r)


@router.put("/trip-reasons/{reason_id}")
def update_reason(reason_id: int, body: S.TripReasonIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    r = db.get(TripReason, reason_id)
    if not r:
        raise HTTPException(404, "Reason not found")
    sc.require_company(r.company_id, Role.SCHEDULER, "Reason")
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    audit_service.record(db, sc.user, "UPDATE", "TripReason", reason_id, body.model_dump())
    db.commit()
    return _reason_out(r)


@router.delete("/trip-reasons/{reason_id}", status_code=204)
def delete_reason(reason_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """Only an unused reason can go; one already written on a sheet is deactivated instead."""
    r = db.get(TripReason, reason_id)
    if not r:
        raise HTTPException(404, "Reason not found")
    sc.require_company(r.company_id, Role.SCHEDULER, "Reason")
    used = (db.query(TripSheetRow).filter(TripSheetRow.reason_id == reason_id).first()
            or db.query(TripSheet).filter(TripSheet.bus_change_reason_id == reason_id).first())
    if used:
        raise HTTPException(409, f"Reason {r.reason_code} is used on a trip sheet - deactivate it instead")
    audit_service.record(db, sc.user, "DELETE", "TripReason", reason_id, {"reason_code": r.reason_code})
    db.delete(r)
    db.commit()
