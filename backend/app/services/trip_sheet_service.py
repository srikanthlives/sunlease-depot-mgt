"""Trip sheets: actuals for one schedule on one operating date, entered from the driver's paper sheet.

A sheet points at the exact published version that applied on its date (never copied, never changed).
Billing follows the contract rule: planned km, minus km lost to cancelled or cut-short runs - unless the
loss is attributable to a party the cost center still bills for (setting bill_lost_km_attributable_to).
"""
import datetime as dt
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.enums import ActivityType, CrewMode, CrewRole, Payability, RowStatus, TripSheetStatus
from app.models.models import (
    BusSchedule, Employee, Location, RouteStop, ScheduledActivity, TripReason, TripSheet, TripSheetCrew, TripSheetRow,
    TripSheetStop, Vehicle,
)
from app.services import settings_service
from app.services.schedule_service import Issues, activity_span, shift_span, summarize, version_for_date
from app.services.timeutil import fmt_minutes, rel_minutes

DRIVING = (ActivityType.PASSENGER_TRIP, ActivityType.NON_REVENUE_MOVEMENT)
ODO_GAP_KM = Decimal("0.5")

DEFAULT_REASONS = [  # (code, name, default attribution) - created per company on first use
    ("BREAKDOWN", "Vehicle breakdown", "OPERATOR"), ("ACCIDENT", "Accident", "OPERATOR"),
    ("NO_CREW", "Driver / crew not available", "OPERATOR"), ("CHARGING", "Charging issue / low SOC", "OPERATOR"),
    ("TRAFFIC", "Traffic congestion", "EXTERNAL"), ("ROAD_CLOSED", "Road closure / diversion", "EXTERNAL"),
    ("WEATHER", "Weather", "EXTERNAL"), ("CLIENT", "Client instruction", "CLIENT"), ("OTHER", "Other", "OPERATOR"),
]


def bad(status: int, msg):
    raise HTTPException(status, msg)


def rel(offset, time) -> int | None:
    return rel_minutes(offset or 0, time) if time is not None else None


def ensure_reasons(db: Session, company_id: int) -> None:
    if db.query(TripReason).filter(TripReason.company_id == company_id).first():
        return
    for code, name, attr in DEFAULT_REASONS:
        db.add(TripReason(company_id=company_id, reason_code=code, reason_name=name, default_attributable_to=attr))
    db.flush()


# --------------------------------------------------------------------------
# Creating a sheet
# --------------------------------------------------------------------------
def create_sheet(db: Session, schedule: BusSchedule, on: dt.date, user) -> TripSheet:
    version = version_for_date(schedule, on)
    if version is None:
        bad(422, f"No published version of {schedule.schedule_code} applies on {on.isoformat()}")
    if db.query(TripSheet).filter(TripSheet.schedule_id == schedule.schedule_id, TripSheet.operating_date == on).first():
        bad(409, f"A trip sheet for {schedule.schedule_code} on {on.isoformat()} already exists")
    sheet = TripSheet(cost_center_id=schedule.cost_center_id, schedule_id=schedule.schedule_id,
                      schedule_version_id=version.schedule_version_id, vehicle_id=schedule.vehicle_id,
                      operating_date=on, status=TripSheetStatus.DRAFT, created_by=user.id)
    for a in sorted(version.activities, key=lambda x: x.sequence_number):
        sheet.rows.append(TripSheetRow(activity_id=a.activity_id, row_sequence=a.sequence_number * 10,
                                       status=RowStatus.PENDING))
    # crew slots from the version's crew pattern; duty times default to the plan
    roles = [CrewRole.DRIVER] + ([CrewRole.CONDUCTOR] if version.conductor_required else [])
    if version.crew_mode == CrewMode.SHIFTS and version.shifts:
        for sh in version.shifts:
            for role in roles:
                sheet.crew.append(TripSheetCrew(
                    crew_role=role, shift_id=sh.shift_id, duty_start_day_offset=sh.start_day_offset,
                    duty_start_time=sh.start_time, duty_end_day_offset=sh.end_day_offset, duty_end_time=sh.end_time))
    else:
        summ = summarize(version)
        s, e = summ["operating_start_min"], summ["operating_end_min"]
        for role in roles:
            c = TripSheetCrew(crew_role=role)
            if s is not None:
                c.duty_start_day_offset, c.duty_start_time = s // 1440, dt.time((s % 1440) // 60, s % 60)
                c.duty_end_day_offset, c.duty_end_time = e // 1440, dt.time((e % 1440) // 60, e % 60)
            sheet.crew.append(c)
    db.add(sheet)
    db.flush()
    _prefill_crew_from_roster(db, sheet)
    company = schedule.cost_center.company_id if schedule.cost_center else None
    if company:
        ensure_reasons(db, company)
    return sheet


def _prefill_crew_from_roster(db: Session, sheet: TripSheet) -> int:
    """Fill the crew slots from the duty roster, so the clerk confirms rather than retypes.

    Imported here rather than at the top because the roster reads trip sheets too.
    """
    from app.services.duty_actual_service import crew_for_sheet
    rostered = crew_for_sheet(db, sheet)
    if not rostered:
        return 0
    filled = 0
    for c in sheet.crew:
        who = rostered.get((c.shift_id, c.crew_role))
        # the first person on the slot: a duty handed over part-way is recorded on the sheet
        # with its own crew change, which the clerk makes
        if who and c.employee_id is None:
            c.employee_id = who[0]
            filled += 1
    if filled:
        db.flush()
    return filled


def roster_crew_check(db: Session, sheet: TripSheet) -> dict:
    """Compare the sheet's crew against the duty roster for that bus and date.

    A name is a match when it is anybody the roster has on that slot, because a duty handed over
    part-way was held by two people and either may appear on the sheet.
    """
    from app.services.duty_actual_service import crew_for_sheet
    rostered = crew_for_sheet(db, sheet)
    if not rostered:
        return {"checked": False, "mismatch": False, "rows": []}
    rows = []
    for c in sheet.crew:
        if c.employee_id is None:
            continue
        who = rostered.get((c.shift_id, c.crew_role))
        if not who or c.employee_id in who:
            continue
        names = [e.full_name for e in
                 (db.get(Employee, i) for i in who) if e is not None]
        rows.append({"crew_role": c.crew_role,
                     "shift_name": c.shift.shift_name if c.shift else None,
                     "sheet_name": c.employee.full_name,
                     "sheet_number": c.employee.employee_number,
                     "roster_names": names,
                     "took_over": c.replaces_crew_id is not None})
    return {"checked": True, "mismatch": bool(rows), "rows": rows}


def roster_crew_differences(db: Session, sheet: TripSheet) -> list[str]:
    """The same comparison, worded for the sheet's validation panel."""
    out = []
    for r in roster_crew_check(db, sheet)["rows"]:
        who = " or ".join(r["roster_names"]) or "somebody else"
        slot = r["crew_role"].title() + (f" ({r['shift_name']})" if r["shift_name"] else "")
        out.append(f"{slot}: {r['sheet_name']} worked it, but the duty roster has {who}")
    return out


def assert_editable(sheet: TripSheet):
    if sheet.status != TripSheetStatus.DRAFT:
        bad(409, "Only a draft trip sheet can be changed - return it to draft first")


# --------------------------------------------------------------------------
# Billing
# --------------------------------------------------------------------------
def _stop_km(row: TripSheetRow) -> Decimal | None:
    """Route km from the trip's origin to the stop where a cut-short trip ended."""
    return row.stopped_at.cumulative_distance_km if row.stopped_at else None


def row_billing(row: TripSheetRow, billed_attr: set[str]) -> dict:
    """planned km, km actually run (on the plan), km lost, and km billed for one row."""
    a = row.activity
    out = {"planned_km": 0.0, "run_km": 0.0, "lost_km": 0.0, "lost_billed_km": 0.0, "billable_km": 0.0, "billable": False}
    odo = None
    if row.start_odometer_km is not None and row.end_odometer_km is not None:
        odo = float(row.end_odometer_km - row.start_odometer_km)
    out["odometer_km"] = odo
    if a is None:  # extra (unplanned) run: odometer km, billed only when marked payable
        if row.status in (RowStatus.OPERATED, RowStatus.PARTIAL) and odo is not None and row.extra_payable:
            out.update(run_km=odo, billable_km=odo, billable=True)
        return out
    if a.trip:
        planned, billable = a.trip.planned_distance_km, True
    elif a.movement:
        planned, billable = a.movement.planned_distance_km, a.movement.payability_status == Payability.PAYABLE
    else:
        return out
    run = Decimal(0)
    if row.status == RowStatus.OPERATED:
        run = planned
    elif row.status == RowStatus.PARTIAL:
        run = min(_stop_km(row) or Decimal(0), planned)
    lost = planned - run if row.status in (RowStatus.PARTIAL, RowStatus.CANCELLED) else Decimal(0)
    lost_billed = lost if lost and row.attributable_to in billed_attr else Decimal(0)
    out.update(planned_km=float(planned), run_km=float(run), lost_km=float(lost), lost_billed_km=float(lost_billed),
               billable=billable, billable_km=float(run + lost_billed) if billable else 0.0)
    return out


def summarize_sheet(sheet: TripSheet, cfg: dict) -> dict:
    billed_attr = {x for x in cfg["bill_lost_km_attributable_to"].split(",") if x}
    rows = [(r, row_billing(r, billed_attr)) for r in sheet.rows]
    trips = [(r, b) for r, b in rows if r.activity and r.activity.trip]
    billable_planned = sum(b["planned_km"] for r, b in rows if b["billable"] and r.activity)
    return {
        "planned_trip_km": round(sum(b["planned_km"] for _, b in trips), 2),
        "planned_billable_km": round(billable_planned, 2),
        "billable_km": round(sum(b["billable_km"] for _, b in rows), 2),
        "deducted_km": round(sum(b["lost_km"] - b["lost_billed_km"] for _, b in rows if b["billable"]), 2),
        "lost_billed_km": round(sum(b["lost_billed_km"] for _, b in rows if b["billable"]), 2),
        "odometer_km": round(sum(b["odometer_km"] or 0 for _, b in rows), 1),
        "trips_planned": len(trips),
        "trips_operated": sum(1 for r, _ in trips if r.status == RowStatus.OPERATED),
        "trips_partial": sum(1 for r, _ in trips if r.status == RowStatus.PARTIAL),
        "trips_cancelled": sum(1 for r, _ in trips if r.status == RowStatus.CANCELLED),
        "rows_pending": sum(1 for r, _ in rows if r.status == RowStatus.PENDING),
        "crew_minutes": crew_minutes(sheet),
    }, {r.row_id: b for r, b in rows}


def crew_minutes(sheet: TripSheet) -> dict:
    """Working minutes per crew duty (cut short by a handover)."""
    out = {}
    for c in sheet.crew:
        s, e = rel(c.duty_start_day_offset, c.duty_start_time), rel(c.duty_end_day_offset, c.duty_end_time)
        out[c.crew_id] = max(0, e - s) if s is not None and e is not None else None
    return out


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
def _row_label(r: TripSheetRow) -> str:
    a = r.activity
    if a is None:
        return f"Extra run #{r.row_sequence}"
    if a.trip:
        return f"Trip {a.trip.trip_number}"
    return f"#{a.sequence_number} {a.activity_type.replace('_', ' ').title()}"


def _issue(iss: Issues, sev: str, code: str, msg: str, row: TripSheetRow | None = None):
    iss.items.append({"severity": sev, "code": code, "message": msg, "row_id": row.row_id if row else None,
                      "activity_id": None, "sequence": None})


def own_bus_rows(sheet: TripSheet) -> list[TripSheetRow]:
    """Rows run by the sheet's assigned bus: everything before a bus change (all rows when there is none)."""
    rows = sorted(sheet.rows, key=lambda x: x.row_sequence)
    if sheet.bus_change_from_row_id is None:
        return rows
    cut = next((i for i, r in enumerate(rows) if r.row_id == sheet.bus_change_from_row_id), len(rows))
    return rows[:cut]


def normalise_registration(text: str | None) -> str | None:
    """'AP 39 WU 3580' and 'ap39wu-3580' both become 'AP39WU3580' (the paper has one box per character)."""
    if not text:
        return None
    return "".join(ch for ch in text.upper() if ch.isalnum()) or None


def apply_bus_change(db: Session, sheet: TripSheet, registration: str | None, from_row_id: int | None, reason_id: int | None):
    reg = normalise_registration(registration)
    sheet.bus_change_registration = reg
    sheet.bus_change_vehicle_id = None
    sheet.bus_change_from_row_id = None
    sheet.bus_change_reason_id = None
    if reg is None:
        return
    company = sheet.schedule.cost_center.company_id if sheet.schedule.cost_center else None
    for v in db.query(Vehicle).filter(Vehicle.cost_center_id == sheet.cost_center_id).all():
        if normalise_registration(v.registration_number) == reg:
            sheet.bus_change_vehicle_id = v.vehicle_id
            break
    if from_row_id is not None:
        if from_row_id not in {r.row_id for r in sheet.rows}:
            bad(422, "The bus change run is not on this sheet")
        sheet.bus_change_from_row_id = from_row_id
    if reason_id is not None:
        reason = db.get(TripReason, reason_id)
        if reason is None or reason.company_id != company:
            bad(422, "Unknown reason")
        sheet.bus_change_reason_id = reason_id


def previous_closing(db: Session, sheet: TripSheet) -> dict | None:
    """The bus's closing odometer on its last earlier trip sheet: it stood in the depot (halt) overnight,
    so this is where today's first run should start. Readings taken on a replacement bus don't count."""
    prev = (db.query(TripSheet).filter(TripSheet.vehicle_id == sheet.vehicle_id,
                                       TripSheet.operating_date < sheet.operating_date)
            .order_by(TripSheet.operating_date.desc(), TripSheet.sheet_id.desc()).first())
    if prev is None:
        return None
    readings = [r.end_odometer_km for r in own_bus_rows(prev) if r.end_odometer_km is not None]
    if not readings:
        return None
    return {"sheet_id": prev.sheet_id, "operating_date": prev.operating_date, "odometer_km": readings[-1],
            "status": prev.status}


def validate_sheet(db: Session, sheet: TripSheet) -> dict:
    iss = Issues()
    cfg = settings_service.get_all(db, sheet.cost_center_id)
    tol = float(cfg["odometer_tolerance_pct"])
    err = lambda code, msg, r=None: _issue(iss, "ERROR", code, msg, r)  # noqa: E731
    warn = lambda code, msg, r=None: _issue(iss, "WARNING", code, msg, r)  # noqa: E731
    summary, billing = summarize_sheet(sheet, cfg)

    closing = previous_closing(db, sheet)
    # a replacement bus from the first run means the opening reading is not this bus's
    if sheet.bus_change_from_row_id is not None and not own_bus_rows(sheet):
        closing = None
    _validate_paper(sheet, err, warn)
    prev_end_odo = prev_end_t = None
    prev_row = None
    opening_checked = False
    for r in sorted(sheet.rows, key=lambda x: x.row_sequence):
        label = _row_label(r)
        a = r.activity
        if r.status == RowStatus.PENDING:
            err("ROW_PENDING", f"{label}: not entered yet", r)
            continue
        if r.status == RowStatus.PARTIAL and not (a and a.trip):
            err("PARTIAL_NOT_TRIP", f"{label}: only a passenger trip can be partly operated", r)
        if r.status in (RowStatus.PARTIAL, RowStatus.CANCELLED):
            if r.reason_id is None:
                err("REASON_MISSING", f"{label}: reason required", r)
            if not r.attributable_to:
                err("ATTRIBUTION_MISSING", f"{label}: record who the loss is attributable to", r)
        if r.status == RowStatus.PARTIAL and a and a.trip:
            if r.stopped_at is None:
                err("STOP_MISSING", f"{label}: pick the stop where the trip ended", r)
            elif r.stopped_at.direction_id != a.trip.direction_id:
                err("STOP_WRONG", f"{label}: the stop is not on this trip's direction", r)
        if r.row_id == sheet.bus_change_from_row_id:
            prev_end_odo = None          # another bus from here: its odometer starts a new sequence
        if r.status == RowStatus.CANCELLED:
            continue
        # operated / partial: times and odometer
        s, e = rel(r.actual_start_day_offset, r.actual_start_time), rel(r.actual_end_day_offset, r.actual_end_time)
        if s is None or e is None:
            err("TIME_MISSING", f"{label}: actual start and end times required", r)
        elif e <= s:
            err("TIME_ORDER", f"{label}: end must be after start (check the day offset)", r)
        else:
            if prev_end_t is not None and s < prev_end_t:
                warn("TIME_OVERLAP", f"{label} starts before {_row_label(prev_row)} ended", r)
            prev_end_t, prev_row = e, r
        driving = (a is None) or a.activity_type in DRIVING
        so, eo = r.start_odometer_km, r.end_odometer_km
        if driving:
            if so is None or eo is None:
                warn("ODO_MISSING", f"{label}: start and end odometer not entered", r)
            elif eo < so:
                err("ODO_DECREASE", f"{label}: end odometer is lower than start", r)
            else:
                b = billing[r.row_id]
                expect = b["run_km"] if a is not None else None
                if expect:
                    dev = abs(float(eo - so) - expect) / expect * 100
                    if dev > tol:
                        warn("ODO_DEVIATION", f"{label}: odometer shows {float(eo - so):g} km against {expect:g} km planned "
                                              f"({dev:.0f}% off, tolerance {tol:g}%)", r)
            if so is not None and not opening_checked and closing is not None:
                opening_checked = True
                gap = so - closing["odometer_km"]
                when = closing["operating_date"].isoformat()
                if gap < 0:
                    err("ODO_OVERNIGHT", f"{label}: opening odometer {so} is below the closing reading {closing['odometer_km']} "
                                         f"of {when}", r)
                elif gap > ODO_GAP_KM:
                    warn("ODO_OVERNIGHT", f"{label}: {gap} km not recorded since the closing reading of {when} "
                                          f"({closing['odometer_km']})", r)
            if so is not None and prev_end_odo is not None:
                if so < prev_end_odo:
                    err("ODO_CONTINUITY", f"{label}: start odometer {so} is below the previous end {prev_end_odo}", r)
                elif so - prev_end_odo > ODO_GAP_KM:
                    warn("ODO_GAP", f"{label}: {so - prev_end_odo} km not recorded since the previous run", r)
            if eo is not None:
                prev_end_odo = eo
        # stop-level
        last_odo = None
        for st in r.stops:
            if st.odometer_km is not None:
                if last_odo is not None and st.odometer_km < last_odo:
                    err("STOP_ODO_DECREASE", f"{label}: odometer decreases at stop {st.stop_sequence}", r)
                last_odo = st.odometer_km
        if r.status == RowStatus.PARTIAL and a is None:
            err("PARTIAL_NOT_TRIP", f"{label}: only a passenger trip can be partly operated", r)

    _validate_crew(db, sheet, err, warn)
    for message in roster_crew_differences(db, sheet):
        warn("CREW_OFF_ROSTER", message)
    errors = [i for i in iss.items if i["severity"] == "ERROR"]
    # remembered on the sheet so the daily board can show the warning / error symbol straight away
    sheet.validation_errors, sheet.validation_warnings = len(errors), len(iss.items) - len(errors)
    return {"valid": not errors, "error_count": len(errors),
            "warning_count": len(iss.items) - len(errors), "issues": iss.items, "summary": summary}


def _validate_paper(sheet: TripSheet, err, warn):
    if sheet.paper_version_number and sheet.paper_version_number != sheet.version.version_number:
        warn("PAPER_VERSION", f"The paper is for v{sheet.paper_version_number}, but v{sheet.version.version_number} applies on "
                              f"{sheet.operating_date.isoformat()} - check the runs against the paper")
    if sheet.bus_change_registration:
        if sheet.bus_change_vehicle_id is None:
            warn("BUS_CHANGE_UNKNOWN", f"Bus change: registration {sheet.bus_change_registration} is not in this cost center's bus list")
        elif sheet.bus_change_vehicle_id == sheet.vehicle_id:
            err("BUS_CHANGE_SAME", "Bus change: the registration is the assigned bus itself")
        if sheet.bus_change_from_row_id is None:
            err("BUS_CHANGE_RUN", "Bus change: pick the run from which the other bus operated")
        if sheet.bus_change_reason_id is None:
            err("BUS_CHANGE_REASON", "Bus change: reason required")


def _validate_crew(db: Session, sheet: TripSheet, err, warn):
    on = sheet.operating_date
    duties = {CrewRole.DRIVER: [], CrewRole.CONDUCTOR: []}
    for c in sheet.crew:
        who = f"{c.crew_role.title()}{f' ({c.shift.shift_name})' if c.shift else ''}"
        if c.employee_id is None:
            err("CREW_MISSING", f"{who}: select the employee")
        else:
            e = c.employee
            who = f"{who} {e.full_name}"
            if e.cost_center_id != sheet.cost_center_id:
                err("CREW_COST_CENTER", f"{who} belongs to another cost center")
            if e.staff_type != c.crew_role:
                err("CREW_TYPE", f"{who} is {e.staff_type.lower()}, not a {c.crew_role.lower()}")
            if e.status != "ACTIVE" or e.start_date > on or (e.end_date and e.end_date < on):
                err("CREW_UNAVAILABLE", f"{who} is not employed on {on.isoformat()}")
        s, t = rel(c.duty_start_day_offset, c.duty_start_time), rel(c.duty_end_day_offset, c.duty_end_time)
        if s is None or t is None:
            err("DUTY_TIME", f"{who}: duty start and end required")
        elif t <= s:
            err("DUTY_TIME", f"{who}: duty end must be after start")
        else:
            duties[c.crew_role].append((s, t, c))
    for role, spans in duties.items():
        spans.sort(key=lambda x: x[0])
        for (s1, e1, c1), (s2, e2, c2) in zip(spans, spans[1:]):
            if s2 < e1:
                err("DUTY_OVERLAP", f"Two {role.lower()}s on duty at the same time ({fmt_minutes(e1 - s2)} overlap)")
    # every driven row needs a driver on duty; trips need a conductor when the version requires one
    def covered(spans, s, e):
        t = s
        for a, b, _ in sorted(spans, key=lambda x: x[0]):
            if a <= t < b:
                t = b
            if t >= e:
                return True
        return t >= e
    for r in sheet.rows:
        if r.status not in (RowStatus.OPERATED, RowStatus.PARTIAL):
            continue
        s, e = rel(r.actual_start_day_offset, r.actual_start_time), rel(r.actual_end_day_offset, r.actual_end_time)
        if s is None or e is None or e <= s:
            continue
        if (r.activity is None or r.activity.activity_type in DRIVING) and not covered(duties[CrewRole.DRIVER], s, e):
            warn("NO_DRIVER", f"{_row_label(r)}: no driver on duty for the whole run")
        if sheet.version.conductor_required and r.activity and r.activity.trip and not covered(duties[CrewRole.CONDUCTOR], s, e):
            warn("NO_CONDUCTOR", f"{_row_label(r)}: no conductor on duty for the whole trip")
    # the same person on duty on two sheets at once
    for c in sheet.crew:
        if c.employee_id is None or c.duty_start_time is None or c.duty_end_time is None:
            continue
        a0 = dt.datetime.combine(on, c.duty_start_time) + dt.timedelta(days=c.duty_start_day_offset or 0)
        a1 = dt.datetime.combine(on, c.duty_end_time) + dt.timedelta(days=c.duty_end_day_offset or 0)
        others = (db.query(TripSheetCrew).join(TripSheet).filter(
            TripSheetCrew.employee_id == c.employee_id, TripSheet.sheet_id != sheet.sheet_id,
            TripSheet.operating_date.between(on - dt.timedelta(days=2), on + dt.timedelta(days=2))).all())
        for o in others:
            if o.duty_start_time is None or o.duty_end_time is None:
                continue
            od = o.sheet.operating_date
            b0 = dt.datetime.combine(od, o.duty_start_time) + dt.timedelta(days=o.duty_start_day_offset or 0)
            b1 = dt.datetime.combine(od, o.duty_end_time) + dt.timedelta(days=o.duty_end_day_offset or 0)
            if a0 < b1 and b0 < a1:
                err("CREW_DOUBLE_BOOKED", f"{c.employee.full_name} is also on duty on {o.sheet.schedule.schedule_code} "
                                          f"({od.isoformat()}) at the same time")


# --------------------------------------------------------------------------
# Editing
# --------------------------------------------------------------------------
STATIONARY = (ActivityType.LAYOVER, ActivityType.CHARGING, ActivityType.HALT)


def fill_stationary(sheet: TripSheet) -> dict:
    """Carry the actuals through the rows nobody writes on paper: layovers and halts take their times
    from the runs around them, and layovers, charging and halts take SOC from the previous end and the
    next start. Same rule as the *Fill in layovers & SOC* button on the entry screen, so a scanned
    sheet arrives as complete as a hand-keyed one. Cancelled rows are skipped, and an un-entered
    neighbour blocks the fill on that side rather than reaching further away.
    """
    ordered = sorted(sheet.rows, key=lambda r: r.row_sequence)

    def near(idx: int, step: int, pick):
        j = idx + step
        while 0 <= j < len(ordered):
            r = ordered[j]
            if r.status != RowStatus.CANCELLED:
                return pick(r)
            j += step
        return None

    times = socs = 0
    for idx, r in enumerate(ordered):
        kind = r.activity.activity_type if r.activity else None
        if kind not in STATIONARY or r.status == RowStatus.CANCELLED:
            continue
        before = (r.actual_start_time, r.actual_end_time, r.start_soc_pct, r.end_soc_pct)
        if kind != ActivityType.CHARGING:
            end = near(idx, -1, lambda x: (x.actual_end_day_offset or 0, x.actual_end_time) if x.actual_end_time else None)
            start = near(idx, 1, lambda x: (x.actual_start_day_offset or 0, x.actual_start_time) if x.actual_start_time else None)
            s0 = end or ((r.actual_start_day_offset or 0, r.actual_start_time) if r.actual_start_time else None)
            e0 = start or ((r.actual_end_day_offset or 0, r.actual_end_time) if r.actual_end_time else None)
            if s0 and e0 and rel_minutes(e0[0], e0[1]) > rel_minutes(s0[0], s0[1]):
                r.actual_start_day_offset, r.actual_start_time = s0
                r.actual_end_day_offset, r.actual_end_time = e0
                if r.status == RowStatus.PENDING:
                    r.status = RowStatus.OPERATED
        ps = near(idx, -1, lambda x: x.end_soc_pct)
        ns = near(idx, 1, lambda x: x.start_soc_pct)
        if ps is not None:
            r.start_soc_pct = ps
        if ns is not None:
            r.end_soc_pct = ns
        after = (r.actual_start_time, r.actual_end_time, r.start_soc_pct, r.end_soc_pct)
        if after != before:
            if after[:2] != before[:2]:
                times += 1
            else:
                socs += 1
    return {"times": times, "socs": socs}


def apply_row(db: Session, sheet: TripSheet, r: TripSheetRow, data) -> None:
    for k in ("status", "actual_start_day_offset", "actual_start_time", "actual_end_day_offset", "actual_end_time",
              "start_odometer_km", "end_odometer_km", "start_soc_pct", "end_soc_pct", "energy_kwh",
              "attributable_to", "remarks"):
        setattr(r, k, getattr(data, k))
    company = sheet.schedule.cost_center.company_id if sheet.schedule.cost_center else None
    r.reason_id = None
    if data.reason_id is not None:
        reason = db.get(TripReason, data.reason_id)
        if reason is None or reason.company_id != company:
            bad(422, "Unknown reason")
        r.reason_id = reason.reason_id
        if not r.attributable_to:
            r.attributable_to = reason.default_attributable_to
    r.stopped_at_route_stop_id = None
    if data.stopped_at_route_stop_id is not None:
        if db.get(RouteStop, data.stopped_at_route_stop_id) is None:
            bad(422, "Unknown stop")
        r.stopped_at_route_stop_id = data.stopped_at_route_stop_id
    if r.activity is None:
        for k in ("extra_from_location_id", "extra_to_location_id"):
            v = getattr(data, k)
            if v is not None:
                loc = db.get(Location, v)
                if loc is None or loc.company_id != company:
                    bad(422, "Location does not exist in this company")
            setattr(r, k, v)
        r.extra_payable = bool(data.extra_payable)
    if data.stops is not None:
        if r.activity is None or r.activity.trip is None:
            bad(422, "Stop details apply to passenger trips only")
        valid = {s.scheduled_stop_time_id: s for s in r.activity.stop_times}
        r.stops = []
        db.flush()
        for st in data.stops:
            if st.scheduled_stop_time_id not in valid:
                bad(422, "Stop does not belong to this trip")
            if all(getattr(st, k) is None for k in ("arrival_time", "departure_time", "odometer_km", "soc_pct")):
                continue
            r.stops.append(TripSheetStop(stop_sequence=valid[st.scheduled_stop_time_id].stop_sequence, **st.model_dump()))


def _crew_employee(db: Session, sheet: TripSheet, employee_id: int | None) -> None:
    """Crew must belong to the same cost center as the bus. Checked here as well as in
    validation, so a cross-depot employee can never be saved onto a sheet at all."""
    if employee_id is None:
        return
    e = db.get(Employee, employee_id)
    if e is None:
        bad(422, "Unknown employee")
    if e.cost_center_id != sheet.cost_center_id:
        bad(422, f"{e.full_name} belongs to another cost center")


def apply_crew(db: Session, sheet: TripSheet, c: TripSheetCrew, data) -> None:
    _crew_employee(db, sheet, data.employee_id)
    for k in ("employee_id", "duty_start_day_offset", "duty_start_time", "duty_end_day_offset", "duty_end_time",
              "handover_reason"):
        setattr(c, k, getattr(data, k))


def handover(db: Session, sheet: TripSheet, c: TripSheetCrew, data) -> TripSheetCrew:
    """Driver (or conductor) leaves mid-duty: their duty ends at `at`, a new duty starts at `at`."""
    at = rel(data.at_day_offset, data.at_time)
    s, e = rel(c.duty_start_day_offset, c.duty_start_time), rel(c.duty_end_day_offset, c.duty_end_time)
    if s is None or e is None or not (s < at < e):
        bad(422, "The change time must fall inside the current duty")
    _crew_employee(db, sheet, data.employee_id)
    new = TripSheetCrew(sheet_id=sheet.sheet_id, crew_role=c.crew_role, shift_id=c.shift_id, employee_id=data.employee_id,
                        duty_start_day_offset=data.at_day_offset, duty_start_time=data.at_time,
                        duty_end_day_offset=c.duty_end_day_offset, duty_end_time=c.duty_end_time,
                        replaces_crew_id=c.crew_id, handover_reason=data.reason)
    c.duty_end_day_offset, c.duty_end_time = data.at_day_offset, data.at_time
    db.add(new)
    db.flush()
    return new


def _crew_check_brief(db: Session, sheet: TripSheet | None) -> dict:
    """Whether this sheet's crew disagrees with the duty roster, for the board's warning mark."""
    if sheet is None:
        return {"crew_mismatch": False, "crew_mismatch_text": None}
    check = roster_crew_check(db, sheet)
    if not check["mismatch"]:
        return {"crew_mismatch": False, "crew_mismatch_text": None}
    parts = [f"{r['crew_role'].title()}: sheet has {r['sheet_name']}, duty roster has "
             f"{' or '.join(r['roster_names']) or 'nobody'}" for r in check["rows"]]
    return {"crew_mismatch": True, "crew_mismatch_text": "; ".join(parts)}


def board(db: Session, schedules: list[BusSchedule], on: dt.date) -> list[dict]:
    sheets = {s.schedule_id: s for s in db.query(TripSheet).filter(TripSheet.operating_date == on,
                                                                   TripSheet.schedule_id.in_([x.schedule_id for x in schedules]))}
    out = []
    for s in schedules:
        v = version_for_date(s, on)
        sh = sheets.get(s.schedule_id)
        if v is None and sh is None:
            continue
        out.append({"schedule_id": s.schedule_id, "cost_center_id": s.cost_center_id, "schedule_code": s.schedule_code,
                    "schedule_name": s.schedule_name, "fleet_number": s.vehicle.fleet_number,
                    "version_number": (sh.version if sh else v).version_number,
                    "sheet_id": sh.sheet_id if sh else None, "status": sh.status if sh else "NOT_STARTED",
                    "paper_sheet_no": sh.paper_sheet_no if sh else None,
                    "validation_errors": sh.validation_errors if sh else 0,
                    "validation_warnings": sh.validation_warnings if sh else 0,
                    "from_scan": bool(sh.scanned_page_id) if sh else False,
                    **_crew_check_brief(db, sh)})
    return out


def activity_planned(a: ScheduledActivity | None) -> dict | None:
    if a is None:
        return None
    s, e = activity_span(a)
    out = {"activity_id": a.activity_id, "sequence_number": a.sequence_number, "activity_type": a.activity_type,
           "origin_code": a.origin.location_code, "destination_code": a.destination.location_code,
           "origin_name": a.origin.location_name, "destination_name": a.destination.location_name,
           "origin_name_local": a.origin.location_name_local, "destination_name_local": a.destination.location_name_local,
           "start_day_offset": a.start_day_offset, "start_time": a.scheduled_start_time.strftime("%H:%M"),
           "end_day_offset": a.end_day_offset, "end_time": a.scheduled_end_time.strftime("%H:%M"),
           "start_min": s, "end_min": e}
    if a.trip:
        t = a.trip
        out.update(trip_number=t.trip_number, route_code=t.route.route_code, direction_code=t.direction.direction_code,
                   planned_km=float(t.planned_distance_km),
                   stops=[{"scheduled_stop_time_id": st.scheduled_stop_time_id, "route_stop_id": st.route_stop_id,
                           "stop_sequence": st.stop_sequence, "location_code": st.route_stop.location.location_code,
                           "location_name": st.route_stop.location.location_name,
                           "cumulative_km": float(st.route_stop.cumulative_distance_km),
                           "arrival": st.scheduled_arrival_time.strftime("%H:%M") if st.scheduled_arrival_time else None,
                           "arrival_day_offset": st.arrival_day_offset,
                           "departure": st.scheduled_departure_time.strftime("%H:%M") if st.scheduled_departure_time else None,
                           "departure_day_offset": st.departure_day_offset}
                          for st in sorted(a.stop_times, key=lambda x: x.stop_sequence)])
    elif a.movement:
        out.update(planned_km=float(a.movement.planned_distance_km), payability_status=a.movement.payability_status,
                   movement_purpose=a.movement.movement_purpose)
    else:
        out["planned_km"] = 0.0
    return out


def crew_shift_span(c: TripSheetCrew):
    return shift_span(c.shift) if c.shift else None
