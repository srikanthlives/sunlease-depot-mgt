import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.access import Scope, scope
from app.db.session import get_db
from app.models.enums import Role, ScheduleStatus, VersionStatus
from app.models.models import BusSchedule, ScheduledActivity, ScheduleVersion, User, Vehicle
from app.schemas import schemas as S
from app.services import audit_service
from app.services import schedule_service as svc

router = APIRouter(prefix="/api", tags=["schedules"])


def _get_schedule(db, sc: Scope, schedule_id, minimum=Role.VIEWER) -> BusSchedule:
    s = db.get(BusSchedule, schedule_id)
    if not s:
        raise HTTPException(404, "Schedule not found")
    sc.require(s.cost_center_id, minimum, "Schedule")
    return s


def _get_version(db, sc: Scope, version_id, minimum=Role.VIEWER) -> ScheduleVersion:
    v = db.get(ScheduleVersion, version_id)
    if not v:
        raise HTTPException(404, "Schedule version not found")
    sc.require(v.schedule.cost_center_id, minimum, "Schedule version")
    return v


def _get_activity(db, sc: Scope, activity_id, minimum=Role.VIEWER) -> ScheduledActivity:
    a = db.get(ScheduledActivity, activity_id)
    if not a:
        raise HTTPException(404, "Activity not found")
    sc.require(a.version.schedule.cost_center_id, minimum, "Activity")
    return a


def _effective_status(v: ScheduleVersion, today: dt.date) -> str:
    """What the version means today: DRAFT, SCHEDULED (starts later), LIVE, or ENDED."""
    if v.status == VersionStatus.DRAFT:
        return "DRAFT"
    if v.valid_from > today:
        return "SCHEDULED"
    if v.valid_to is not None and v.valid_to < today:
        return "ENDED"
    return "LIVE"


def _shift_out(sh) -> dict:
    return {"shift_id": sh.shift_id, "shift_number": sh.shift_number, "shift_name": sh.shift_name,
            "start_day_offset": sh.start_day_offset, "start_time": sh.start_time.strftime("%H:%M"),
            "end_day_offset": sh.end_day_offset, "end_time": sh.end_time.strftime("%H:%M"),
            "change_location_id": sh.change_location_id}


def _version_brief(v: ScheduleVersion) -> dict:
    return {"schedule_version_id": v.schedule_version_id, "schedule_id": v.schedule_id,
            "version_number": v.version_number, "valid_from": v.valid_from, "valid_to": v.valid_to,
            "status": v.status, "effective_status": _effective_status(v, dt.date.today()),
            "published_at": v.published_at, "published_by": v.published_by,
            "change_reason": v.change_reason, "activity_count": len(v.activities)}


def _schedule_out(s: BusSchedule) -> dict:
    return {"schedule_id": s.schedule_id, "cost_center_id": s.cost_center_id,
            "schedule_code": s.schedule_code, "schedule_name": s.schedule_name,
            "vehicle_id": s.vehicle_id, "fleet_number": s.vehicle.fleet_number,
            "registration_number": s.vehicle.registration_number,
            "home_depot_id": s.vehicle.home_depot_id,
            "recurrence_type": s.recurrence_type, "effective_from": s.effective_from, "effective_to": s.effective_to,
            "timezone": s.timezone, "status": s.status, "updated_at": s.updated_at,
            "versions": [_version_brief(v) for v in s.versions]}


def _activity_out(a: ScheduledActivity) -> dict:
    out = {"activity_id": a.activity_id, "sequence_number": a.sequence_number, "activity_type": a.activity_type,
           "origin_location_id": a.origin_location_id, "destination_location_id": a.destination_location_id,
           "origin_code": a.origin.location_code, "destination_code": a.destination.location_code,
           "origin_name": a.origin.location_name, "destination_name": a.destination.location_name,
           "start_day_offset": a.start_day_offset, "scheduled_start_time": a.scheduled_start_time.strftime("%H:%M"),
           "end_day_offset": a.end_day_offset, "scheduled_end_time": a.scheduled_end_time.strftime("%H:%M"),
           "remarks": a.remarks, "distance_km": float(svc.activity_km(a))}
    start, end = svc.activity_span(a)
    out["start_min"], out["end_min"] = start, end
    if a.trip:
        t = a.trip
        out["trip"] = {
            "trip_number": t.trip_number, "route_id": t.route_id, "direction_id": t.direction_id,
            "route_code": t.route.route_code, "direction_code": t.direction.direction_code,
            "planned_distance_km": t.planned_distance_km, "planned_start_soc_pct": t.planned_start_soc_pct,
            "planned_end_soc_pct": t.planned_end_soc_pct,
            "stops": [{"scheduled_stop_time_id": s.scheduled_stop_time_id, "route_stop_id": s.route_stop_id,
                       "stop_sequence": s.stop_sequence, "location_code": s.route_stop.location.location_code,
                       "location_name": s.route_stop.location.location_name,
                       "arrival_day_offset": s.arrival_day_offset,
                       "scheduled_arrival_time": s.scheduled_arrival_time.strftime("%H:%M") if s.scheduled_arrival_time else None,
                       "departure_day_offset": s.departure_day_offset,
                       "scheduled_departure_time": s.scheduled_departure_time.strftime("%H:%M") if s.scheduled_departure_time else None,
                       "planned_soc_pct": s.planned_soc_pct}
                      for s in a.stop_times]}
    if a.movement:
        m = a.movement
        out["movement"] = {c: getattr(m, c) for c in (
            "movement_purpose", "planned_distance_km",
            "planned_start_soc_pct", "planned_end_soc_pct", "payability_status", "payment_basis")}
    if a.charging:
        c = a.charging
        out["charging"] = {k: getattr(c, k) for k in (
            "charging_location_id", "planned_start_soc_pct", "planned_end_soc_pct", "expected_energy_kwh")}
    if a.halt:
        out["halt"] = {k: getattr(a.halt, k) for k in ("location_id", "planned_start_soc_pct", "planned_end_soc_pct")}
    if a.layover:
        out["layover"] = {k: getattr(a.layover, k) for k in ("location_id", "layover_purpose", "planned_start_soc_pct",
                                                        "planned_end_soc_pct")}
    return out


def _version_detail(v: ScheduleVersion) -> dict:
    s = v.schedule
    return {**_version_brief(v), "cost_center_id": s.cost_center_id, "schedule_code": s.schedule_code, "schedule_name": s.schedule_name,
            "vehicle_id": s.vehicle_id, "fleet_number": s.vehicle.fleet_number, "timezone": s.timezone,
            "recurrence_type": s.recurrence_type, "effective_from": s.effective_from, "effective_to": s.effective_to,
            "crew_mode": v.crew_mode, "conductor_required": v.conductor_required,
            "shifts": [_shift_out(sh) for sh in v.shifts],
            "activities": [_activity_out(a) for a in sorted(v.activities, key=lambda a: a.sequence_number)],
            "summary": svc.summarize(v)}


# ---------------- schedules ----------------
@router.get("/schedules")
def list_schedules(code: str | None = None, vehicle_id: int | None = None, depot_id: int | None = None,
                   status: str | None = None, on_date: dt.date | None = None, activity_type: str | None = None,
                   db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    q = sc.filter(db.query(BusSchedule).join(Vehicle), BusSchedule.cost_center_id)
    if code:
        q = q.filter(BusSchedule.schedule_code.ilike(f"%{code}%"))
    if vehicle_id:
        q = q.filter(BusSchedule.vehicle_id == vehicle_id)
    if depot_id:
        q = q.filter(Vehicle.home_depot_id == depot_id)
    if status:
        q = q.filter(BusSchedule.status == status)
    out = []
    for s in q.order_by(BusSchedule.schedule_code).all():
        if on_date and svc.version_for_date(s, on_date) is None:
            continue
        if activity_type and not any(a.activity_type == activity_type for v in s.versions for a in v.activities):
            continue
        out.append(_schedule_out(s))
    return out


@router.post("/schedules", status_code=201)
def create_schedule(body: S.ScheduleIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    cc = sc.target(Role.SCHEDULER)
    user = sc.user
    vehicle = db.get(Vehicle, body.vehicle_id)
    if not vehicle or vehicle.cost_center_id != cc:
        raise HTTPException(422, "Vehicle does not exist in this cost center")
    if vehicle.status != "ACTIVE":
        raise HTTPException(422, "Vehicle is not active")
    s = BusSchedule(**body.model_dump(), cost_center_id=cc, status=ScheduleStatus.DRAFT, created_by=user.id,
                    updated_by=user.id)
    db.add(s)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Schedule code {body.schedule_code} already exists")
    v = ScheduleVersion(schedule_id=s.schedule_id, version_number=1, valid_from=body.effective_from,
                        valid_to=body.effective_to, status=VersionStatus.DRAFT, created_by=user.id)
    db.add(v)
    db.flush()
    audit_service.record(db, user, "CREATE", "BusSchedule", s.schedule_id, body.model_dump())
    db.commit()
    db.refresh(s)
    return _schedule_out(s)


@router.post("/schedules/{schedule_id}/clone", status_code=201)
def clone_schedule(schedule_id: int, body: S.ScheduleCloneIn, db: Session = Depends(get_db),
                   sc: Scope = Depends(scope)):
    """Copy a schedule onto another bus as a fresh draft.

    The copy starts at version 1 in draft, carrying the source's runs, crew pattern and shifts, so a
    second bus running the same pattern is set up by editing rather than typing it again. Nothing is
    published: the draft is validated and published like any other.
    """
    src = _get_schedule(db, sc, schedule_id, Role.SCHEDULER)
    user = sc.user
    vehicle = db.get(Vehicle, body.vehicle_id)
    if not vehicle or vehicle.cost_center_id != src.cost_center_id:
        raise HTTPException(422, "Vehicle does not exist in this cost center")
    if vehicle.status != "ACTIVE":
        raise HTTPException(422, "Vehicle is not active")
    if body.copy_from_version_id:
        source_version = _get_version(db, sc, body.copy_from_version_id)
        if source_version.schedule_id != schedule_id:
            raise HTTPException(422, "Source version belongs to another schedule")
    else:
        source_version = svc.version_for_date(src, body.effective_from) or next(
            (v for v in reversed(src.versions) if v.status != VersionStatus.DRAFT), None) or (
            src.versions[-1] if src.versions else None)
    if source_version is None:
        raise HTTPException(409, "This schedule has nothing to copy yet")

    s = BusSchedule(schedule_code=body.schedule_code, schedule_name=body.schedule_name, vehicle_id=vehicle.vehicle_id,
                    recurrence_type=src.recurrence_type, timezone=src.timezone, effective_from=body.effective_from,
                    effective_to=body.effective_to, cost_center_id=src.cost_center_id, status=ScheduleStatus.DRAFT,
                    created_by=user.id, updated_by=user.id)
    db.add(s)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Schedule code {body.schedule_code} already exists")
    v = ScheduleVersion(schedule_id=s.schedule_id, version_number=1, valid_from=body.effective_from,
                        valid_to=body.effective_to, status=VersionStatus.DRAFT,
                        change_reason=f"Cloned from {src.schedule_code} v{source_version.version_number}",
                        created_by=user.id)
    db.add(v)
    db.flush()
    svc.copy_version_content(db, source_version, v)
    audit_service.record(db, user, "CREATE", "BusSchedule", s.schedule_id,
                         {"cloned_from": src.schedule_code, "version": source_version.version_number,
                          "schedule_code": body.schedule_code})
    db.commit()
    db.refresh(s)
    return _schedule_out(s)


@router.get("/schedules/{schedule_id}")
def get_schedule(schedule_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    return _schedule_out(_get_schedule(db, sc, schedule_id))


@router.put("/schedules/{schedule_id}")
def update_schedule(schedule_id: int, body: S.ScheduleUpdate, db: Session = Depends(get_db),
                    sc: Scope = Depends(scope)):
    s = _get_schedule(db, sc, schedule_id, Role.SCHEDULER)
    user = sc.user
    data = body.model_dump(exclude_unset=True)
    if data.get("status") == "RETIRED" and sc.rank(s.cost_center_id) < Role.RANK[Role.PUBLISHER]:
        raise HTTPException(403, "Only a publisher can retire a schedule")
    if data.get("effective_from"):
        try:
            svc.change_effective_from(db, s, data.pop("effective_from"))
        except HTTPException:
            db.rollback()
            raise
        data_log = {**data, "effective_from": s.effective_from}
    else:
        data.pop("effective_from", None)
        data_log = data
    if "effective_to" in data and data["effective_to"] and data["effective_to"] < s.effective_from:
        db.rollback()
        raise HTTPException(422, "effective_to cannot be before effective_from")
    last = svc.last_trip_sheet_date(db, schedule_id)
    if last and data.get("effective_to") and data["effective_to"] < last:
        raise HTTPException(409, f"Trip sheets exist up to {last.isoformat()} - effective to cannot be earlier")
    for k, v in data.items():
        setattr(s, k, v)
    s.updated_by = user.id
    audit_service.record(db, user, "UPDATE", "BusSchedule", schedule_id, data_log)
    db.commit()
    return _schedule_out(s)


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(schedule_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """Only schedules that were never published (every version still a draft) can be deleted."""
    s = _get_schedule(db, sc, schedule_id, Role.SCHEDULER)
    user = sc.user
    if any(v.status != VersionStatus.DRAFT for v in s.versions):
        raise HTTPException(409, "This schedule has been published - retire it instead (or unpublish it first)")
    audit_service.record(db, user, "DELETE", "BusSchedule", schedule_id, s.schedule_code)
    for v in s.versions:
        db.delete(v)
    db.flush()
    db.delete(s)
    db.commit()


# ---------------- versions ----------------
@router.get("/schedules/{schedule_id}/versions")
def list_versions(schedule_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    return [_version_brief(v) for v in _get_schedule(db, sc, schedule_id).versions]


@router.post("/schedules/{schedule_id}/versions", status_code=201)
def create_version(schedule_id: int, body: S.VersionIn, db: Session = Depends(get_db),
                   sc: Scope = Depends(scope)):
    s = _get_schedule(db, sc, schedule_id, Role.SCHEDULER)
    user = sc.user
    if s.status == ScheduleStatus.RETIRED:
        raise HTTPException(409, "Schedule is retired")
    if any(v.status == VersionStatus.DRAFT for v in s.versions):
        raise HTTPException(409, "A draft version already exists - publish or delete it first")
    src = None
    if body.copy_from_version_id:
        src = _get_version(db, sc, body.copy_from_version_id)
        if src.schedule_id != schedule_id:
            raise HTTPException(422, "Source version belongs to another schedule")
    else:  # default: copy the latest non-draft version so revisions start from the current plan
        done = [v for v in s.versions if v.status != VersionStatus.DRAFT]
        src = done[-1] if done else None
    v = ScheduleVersion(schedule_id=schedule_id, version_number=max((x.version_number for x in s.versions), default=0) + 1,
                        valid_from=body.valid_from, valid_to=body.valid_to, status=VersionStatus.DRAFT,
                        change_reason=body.change_reason, created_by=user.id)
    db.add(v)
    db.flush()
    if src:
        svc.copy_version_content(db, src, v)
    audit_service.record(db, user, "CREATE", "ScheduleVersion", v.schedule_version_id,
                         {"schedule_id": schedule_id, "version": v.version_number})
    db.commit()
    db.refresh(v)
    return _version_detail(v)


@router.get("/schedule-versions/{version_id}")
def get_version(version_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    return _version_detail(_get_version(db, sc, version_id))


@router.put("/schedule-versions/{version_id}")
def update_version(version_id: int, body: S.VersionUpdate, db: Session = Depends(get_db),
                   sc: Scope = Depends(scope)):
    v = _get_version(db, sc, version_id, Role.SCHEDULER)
    user = sc.user
    svc.assert_draft(v)
    data = body.model_dump(exclude_unset=True)
    for k, val in data.items():
        setattr(v, k, val)
    if v.valid_to and v.valid_to < v.valid_from:
        db.rollback()
        raise HTTPException(422, "valid_to cannot be before valid_from")
    audit_service.record(db, user, "UPDATE", "ScheduleVersion", version_id, data)
    db.commit()
    return _version_detail(v)


@router.delete("/schedule-versions/{version_id}", status_code=204)
def delete_version(version_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    v = _get_version(db, sc, version_id, Role.SCHEDULER)
    user = sc.user
    svc.assert_draft(v)
    audit_service.record(db, user, "DELETE", "ScheduleVersion", version_id, {"schedule_id": v.schedule_id})
    db.delete(v)
    db.commit()


@router.put("/schedule-versions/{version_id}/crew")
def set_crew(version_id: int, body: S.CrewConfigIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """Crew pattern for trip sheets: one driver for the day, or shifts (versioned with the schedule)."""
    v = _get_version(db, sc, version_id, Role.SCHEDULER)
    try:
        svc.set_crew(db, v, body.crew_mode, body.conductor_required, body.shifts)
    except HTTPException:
        db.rollback()
        raise
    audit_service.record(db, sc.user, "UPDATE", "ScheduleVersion", version_id, {"crew": body.model_dump(mode="json")})
    db.commit()
    db.refresh(v)
    return _version_detail(v)


@router.post("/schedule-versions/{version_id}/fill-layovers")
def fill_layovers(version_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """Snap layovers to the activities around them (times and SOC) and fill idle gaps with layovers."""
    v = _get_version(db, sc, version_id, Role.SCHEDULER)
    try:
        result = svc.fill_layovers(db, v)
    except HTTPException:
        db.rollback()
        raise
    audit_service.record(db, sc.user, "UPDATE", "ScheduleVersion", version_id, {"fill_layovers": result})
    db.commit()
    db.refresh(v)
    return {"result": result, "version": _version_detail(v)}


# ---------------- activities ----------------
@router.post("/schedule-versions/{version_id}/activities", status_code=201)
def add_activity(version_id: int, body: S.ActivityIn, db: Session = Depends(get_db),
                 sc: Scope = Depends(scope)):
    v = _get_version(db, sc, version_id, Role.SCHEDULER)
    user = sc.user
    try:
        a = svc.add_activity(db, v, body)
        audit_service.record(db, user, "CREATE", "ScheduledActivity", a.activity_id,
                             {"version": version_id, "type": a.activity_type, "seq": a.sequence_number})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, f"Activity conflicts with existing data: {str(exc.orig)[:160]}")
    except HTTPException:
        db.rollback()
        raise
    db.refresh(a)
    return _activity_out(a)


@router.post("/schedule-versions/{version_id}/activities/reorder")
def reorder_activities(version_id: int, body: S.ReorderIn, db: Session = Depends(get_db),
                       sc: Scope = Depends(scope)):
    v = _get_version(db, sc, version_id, Role.SCHEDULER)
    user = sc.user
    try:
        svc.reorder(db, v, body.activity_ids)
    except HTTPException:
        db.rollback()
        raise
    audit_service.record(db, user, "UPDATE", "ScheduleVersion", version_id, {"reorder": body.activity_ids})
    db.commit()
    db.refresh(v)
    return _version_detail(v)


@router.get("/activities/{activity_id}")
def get_activity(activity_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    return _activity_out(_get_activity(db, sc, activity_id))


@router.put("/activities/{activity_id}")
def update_activity(activity_id: int, body: S.ActivityIn, db: Session = Depends(get_db),
                    sc: Scope = Depends(scope)):
    a = _get_activity(db, sc, activity_id, Role.SCHEDULER)
    user = sc.user
    try:
        svc.update_activity(db, a, body)
        audit_service.record(db, user, "UPDATE", "ScheduledActivity", activity_id, {"type": a.activity_type})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, f"Activity conflicts with existing data: {str(exc.orig)[:160]}")
    except HTTPException:
        db.rollback()
        raise
    db.refresh(a)
    return _activity_out(a)


@router.delete("/activities/{activity_id}", status_code=204)
def delete_activity(activity_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    a = _get_activity(db, sc, activity_id, Role.SCHEDULER)
    user = sc.user
    try:
        svc.delete_activity(db, a)
    except HTTPException:
        db.rollback()
        raise
    audit_service.record(db, user, "DELETE", "ScheduledActivity", activity_id, None)
    db.commit()


# ---------------- validate / publish ----------------
@router.post("/schedule-versions/{version_id}/validate")
def validate(version_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    return svc.validate_version(db, _get_version(db, sc, version_id))


@router.post("/schedule-versions/{version_id}/publish")
def publish(version_id: int, body: S.PublishIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    v = _get_version(db, sc, version_id, Role.PUBLISHER)
    user = sc.user
    try:
        result = svc.publish(db, v, user, body.change_reason, body.acknowledge_warnings)
        audit_service.record(db, user, "PUBLISH", "ScheduleVersion", version_id,
                             {"schedule": v.schedule.schedule_code, "version": v.version_number,
                              "reason": body.change_reason, "warnings_acknowledged": body.acknowledge_warnings,
                              "warnings": result["warning_count"]})
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    db.refresh(v)
    return {"version": _version_brief(v), "validation": result}


@router.post("/schedule-versions/{version_id}/unpublish")
def unpublish(version_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    v = _get_version(db, sc, version_id, Role.PUBLISHER)
    user = sc.user
    try:
        svc.unpublish(db, v, user)
        audit_service.record(db, user, "UNPUBLISH", "ScheduleVersion", version_id,
                             {"schedule": v.schedule.schedule_code, "version": v.version_number})
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    db.refresh(v)
    return _version_brief(v)


# ---------------- timeline / print ----------------
@router.get("/schedules/{schedule_id}/timeline")
def schedule_timeline(schedule_id: int, date: dt.date | None = None, db: Session = Depends(get_db),
                      sc: Scope = Depends(scope)):
    s = _get_schedule(db, sc, schedule_id)
    on = date or dt.date.today()
    v = svc.version_for_date(s, on)
    if v is None:
        raise HTTPException(404, f"No published version of {s.schedule_code} applies on {on.isoformat()}")
    return svc.build_timeline(v, on)


@router.get("/schedule-versions/{version_id}/timeline")
def version_timeline(version_id: int, date: dt.date | None = None, db: Session = Depends(get_db),
                     sc: Scope = Depends(scope)):
    v = _get_version(db, sc, version_id)
    return svc.build_timeline(v, date or v.valid_from)


@router.get("/schedule-versions/{version_id}/print")
def print_view(version_id: int, date: dt.date | None = None, db: Session = Depends(get_db),
               sc: Scope = Depends(scope)):
    v = _get_version(db, sc, version_id)
    tl = svc.build_timeline(v, date or v.valid_from)
    tl["printed_at"] = dt.datetime.utcnow().isoformat()
    return tl
