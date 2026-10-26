import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.access import Scope, scope
from app.db.session import get_db
from app.models.enums import Role, RosterStatus, StaffType
from app.models.models import (
    DutyActual, DutyExtra, DutyPattern, DutyRoster, DutyRosterVersion, Employee,
)
from app.schemas import schemas as S
from app.services import audit_service, availability_service, roster_service
from app.services import duty_actual_service as da
from app.services import duty_pattern_service as dp
from app.services import roster_publish_service as rp

router = APIRouter(prefix="/api", tags=["rosters"])


def _roster(db: Session, sc: Scope, roster_id: int, minimum: str) -> DutyRoster:
    r = db.get(DutyRoster, roster_id)
    if r is None:
        raise HTTPException(404, "Roster not found")
    sc.require(r.cost_center_id, minimum, "Roster")
    return r


def _version(db: Session, sc: Scope, roster: DutyRoster, roster_version_id: int | None) -> DutyRosterVersion:
    """A named version, else the draft, else the live one."""
    if roster_version_id is not None:
        v = db.get(DutyRosterVersion, roster_version_id)
        if v is None or v.roster_id != roster.roster_id:
            raise HTTPException(404, "Roster version not found")
        return v
    v = roster_service.draft_version(roster) or roster_service.live_version(roster)
    if v is None:
        raise HTTPException(404, "This roster has no version yet")
    return v


def _roster_out(r: DutyRoster) -> dict:
    return {"roster_id": r.roster_id, "cost_center_id": r.cost_center_id, "roster_code": r.roster_code,
            "roster_name": r.roster_name, "period_from": r.period_from, "period_to": r.period_to,
            "locked_through": r.locked_through,
            "versions": [{"roster_version_id": v.roster_version_id, "version_number": v.version_number,
                          "status": v.status, "published_at": v.published_at,
                          "change_reason": v.change_reason,
                          "assignments": len(v.assignments)}
                         for v in sorted(r.versions, key=lambda x: x.version_number)]}


@router.get("/rosters", response_model=list[S.RosterOut])
def list_rosters(db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    rows = (sc.filter(db.query(DutyRoster), DutyRoster.cost_center_id)
            .order_by(DutyRoster.period_from.desc()).all())
    return [_roster_out(r) for r in rows]


@router.post("/rosters", response_model=S.RosterOut, status_code=201)
def create_roster(body: S.RosterIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    cc = sc.target(Role.SCHEDULER)
    r = roster_service.create_roster(db, cc, body.roster_code, body.roster_name,
                                     body.period_from, body.period_to, sc.user)
    audit_service.record(db, sc.user, "CREATE", "DutyRoster", r.roster_id, body.model_dump(mode="json"))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, f"Roster conflicts with an existing record: {str(exc.orig)[:160]}")
    return _roster_out(r)


@router.delete("/rosters/{roster_id}", status_code=204)
def delete_roster(roster_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """Remove a roster created by mistake. Refused once it has been published or worked to,
    because by then it is part of the record - supersede it with a revision instead."""
    r = _roster(db, sc, roster_id, Role.SCHEDULER)
    published = [v.version_number for v in r.versions if v.status != RosterStatus.DRAFT]
    if published:
        raise HTTPException(409, f"Version(s) {', '.join(map(str, published))} have been published: "
                                 "a published roster cannot be deleted")
    recorded = db.query(DutyActual).filter(DutyActual.roster_id == roster_id).count()
    if recorded:
        raise HTTPException(409, f"{recorded} duty day(s) have actuals recorded against this roster")
    audit_service.record(db, sc.user, "DELETE", "DutyRoster", roster_id,
                         {"roster_code": r.roster_code, "period_from": str(r.period_from),
                          "period_to": str(r.period_to)})
    db.query(DutyActual).filter(DutyActual.roster_id == roster_id).delete()
    db.delete(r)
    db.commit()
    return Response(status_code=204)


@router.get("/rosters/{roster_id}/grid")
def roster_grid(roster_id: int, roster_version_id: int | None = None, actuals: bool = False,
                db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """The whole matrix: duty slots down, dates across. What the roster screen draws.

    With `actuals`, each cell also carries what was recorded that day, so the one grid shows
    the plan against what happened.
    """
    r = _roster(db, sc, roster_id, Role.VIEWER)
    return roster_service.grid(db, r, _version(db, sc, r, roster_version_id), with_actuals=actuals)


@router.put("/rosters/{roster_id}/assignments")
def set_assignments(roster_id: int, body: S.AssignmentsIn, db: Session = Depends(get_db),
                    sc: Scope = Depends(scope)):
    """Save one or more cells of the draft grid, then hand back the fresh grid."""
    r = _roster(db, sc, roster_id, Role.SCHEDULER)
    v = roster_service.draft_version(r)
    if v is None:
        raise HTTPException(409, "This roster has no draft version to change")
    for cell in body.cells:
        roster_service.set_assignment(db, r, v, cell.duty_date, cell.schedule_id, cell.shift_number,
                                      cell.crew_role, cell.employee_id, cell.remarks)
    audit_service.record(db, sc.user, "UPDATE", "DutyRosterVersion", v.roster_version_id,
                         {"cells": len(body.cells), "dates": sorted({str(c.duty_date) for c in body.cells})})
    db.commit()
    return roster_service.grid(db, r, v)


@router.post("/rosters/{roster_id}/copy-days")
def copy_days(roster_id: int, body: S.CopyDaysIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """'Copy previous week': repeat a stretch of days onto another stretch."""
    r = _roster(db, sc, roster_id, Role.SCHEDULER)
    v = roster_service.draft_version(r)
    if v is None:
        raise HTTPException(409, "This roster has no draft version to change")
    result = roster_service.copy_days(db, r, v, body.source_from, body.target_from, body.day_count)
    audit_service.record(db, sc.user, "COPY", "DutyRosterVersion", v.roster_version_id,
                         body.model_dump(mode="json") | result)
    db.commit()
    return result | roster_service.grid(db, r, v)


def _draft(db: Session, sc: Scope, roster_id: int):
    r = _roster(db, sc, roster_id, Role.SCHEDULER)
    v = roster_service.draft_version(r)
    if v is None:
        raise HTTPException(409, "This roster has no draft version to change")
    return r, v


@router.post("/rosters/{roster_id}/repeat-block")
def repeat_block(roster_id: int, body: S.RepeatBlockIn, db: Session = Depends(get_db),
                 sc: Scope = Depends(scope)):
    """Repeat a typed block of days (the first week by default) across the rest of the period."""
    r, v = _draft(db, sc, roster_id)
    result = roster_service.repeat_block(db, r, v, body.source_from, body.day_count)
    audit_service.record(db, sc.user, "REPEAT", "DutyRosterVersion", v.roster_version_id, result)
    db.commit()
    return result | roster_service.grid(db, r, v)


@router.post("/rosters/{roster_id}/extras", status_code=201)
def add_extra(roster_id: int, body: S.ExtraIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """Add a spare or a shunting driver to one day."""
    r, v = _draft(db, sc, roster_id)
    roster_service.add_extra(db, r, v, body.duty_date, body.duty_type, body.crew_role,
                             body.employee_id, body.start_time, body.end_time, body.remarks)
    audit_service.record(db, sc.user, "CREATE", "DutyExtra", v.roster_version_id,
                         body.model_dump(mode="json"))
    db.commit()
    return roster_service.grid(db, r, v)


def _extra(db: Session, roster: DutyRoster, extra_id: int) -> DutyExtra:
    x = db.get(DutyExtra, extra_id)
    if x is None or x.version.roster_id != roster.roster_id:
        raise HTTPException(404, "Duty not found on this roster")
    return x


@router.put("/rosters/{roster_id}/extras/{extra_id}")
def update_extra(roster_id: int, extra_id: int, body: S.ExtraUpdateIn, db: Session = Depends(get_db),
                 sc: Scope = Depends(scope)):
    r, v = _draft(db, sc, roster_id)
    roster_service.update_extra(db, r, v, _extra(db, r, extra_id), body.employee_id,
                                body.start_time, body.end_time, body.remarks)
    audit_service.record(db, sc.user, "UPDATE", "DutyExtra", extra_id, body.model_dump(mode="json"))
    db.commit()
    return roster_service.grid(db, r, v)


@router.delete("/rosters/{roster_id}/extras/{extra_id}")
def delete_extra(roster_id: int, extra_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    r, v = _draft(db, sc, roster_id)
    x = _extra(db, r, extra_id)
    audit_service.record(db, sc.user, "DELETE", "DutyExtra", extra_id,
                         {"duty_date": str(x.duty_date), "duty_type": x.duty_type})
    roster_service.remove_extra(db, r, v, x)
    db.commit()
    return roster_service.grid(db, r, v)


@router.get("/rosters/{roster_id}/crew-options")
def crew_options(roster_id: int, on: dt.date | None = None, db: Session = Depends(get_db),
                 sc: Scope = Depends(scope)):
    """The depot's drivers and conductors for the grid's dropdowns, flagged with whether
    they are free on `on` (stint dates and the availability register)."""
    r = _roster(db, sc, roster_id, Role.VIEWER)
    out = []
    for e in (db.query(Employee)
              .filter(Employee.cost_center_id == r.cost_center_id,
                      Employee.staff_type.in_((StaffType.DRIVER, StaffType.CONDUCTOR)))
              .order_by(Employee.staff_type, Employee.employee_number).all()):
        item = {"employee_id": e.employee_id, "employee_number": e.employee_number,
                "employee_name": e.full_name, "staff_type": e.staff_type,
                "start_date": e.start_date, "end_date": e.end_date, "status": e.status}
        if on is not None:
            free, why = availability_service.free_on(db, e, on)
            item |= {"free": free, "reason": why}
        out.append(item)
    return {"cost_center_id": r.cost_center_id, "on": on, "crew": out}


@router.post("/rosters/{roster_id}/validate")
def validate_roster(roster_id: int, roster_version_id: int | None = None, db: Session = Depends(get_db),
                    sc: Scope = Depends(scope)):
    r = _roster(db, sc, roster_id, Role.VIEWER)
    return roster_service.validate(db, r, _version(db, sc, r, roster_version_id))


@router.get("/rosters/{roster_id}/slots")
def roster_slots(roster_id: int, on: dt.date, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """The duty slots one date needs, with who is free to take them. Feeds the day pickers."""
    r = _roster(db, sc, roster_id, Role.VIEWER)
    slots = roster_service.slots_for_date(roster_service.schedules_of(db, r), on)
    return {"on": on, "slots": [{"schedule_id": s.schedule.schedule_id,
                                 "schedule_code": s.schedule.schedule_code,
                                 "fleet_number": s.schedule.vehicle.fleet_number,
                                 "shift_number": s.shift.shift_number if s.shift else None,
                                 "shift_name": s.shift.shift_name if s.shift else None,
                                 "crew_role": s.crew_role, "slot_label": s.label,
                                 "version_number": s.version.version_number} for s in slots]}


# ---------------- publish, freeze, revise (step 4) ----------------
@router.post("/rosters/{roster_id}/publish")
def publish_roster(roster_id: int, body: S.PublishRosterIn, db: Session = Depends(get_db),
                   sc: Scope = Depends(scope)):
    """Freeze the draft. Errors block; warnings must be confirmed."""
    r = _roster(db, sc, roster_id, Role.PUBLISHER)
    v = roster_service.draft_version(r)
    if v is None:
        raise HTTPException(409, "This roster has no draft version to publish")
    result = rp.publish(db, r, v, sc.user, body.change_reason, body.acknowledge_warnings)
    audit_service.record(db, sc.user, "PUBLISH", "DutyRosterVersion", v.roster_version_id, result)
    db.commit()
    return result


@router.post("/rosters/{roster_id}/unpublish")
def unpublish_roster(roster_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    r = _roster(db, sc, roster_id, Role.PUBLISHER)
    v = roster_service.live_version(r)
    if v is None:
        raise HTTPException(409, "This roster has no published version")
    result = rp.unpublish(db, r, v, sc.user)
    audit_service.record(db, sc.user, "UNPUBLISH", "DutyRosterVersion", v.roster_version_id, result)
    db.commit()
    return result


@router.post("/rosters/{roster_id}/versions", status_code=201)
def new_roster_version(roster_id: int, body: S.NewRosterVersionIn, db: Session = Depends(get_db),
                       sc: Scope = Depends(scope)):
    """Start a revision: a draft copy of the whole period, completed days carried over locked."""
    r = _roster(db, sc, roster_id, Role.SCHEDULER)
    draft = rp.new_version(db, r, sc.user, body.change_reason)
    audit_service.record(db, sc.user, "CREATE", "DutyRosterVersion", draft.roster_version_id,
                         {"version_number": draft.version_number,
                          "change_reason": body.change_reason,
                          "copied": len(draft.assignments)})
    db.commit()
    return roster_service.grid(db, r, draft)


@router.get("/rosters/{roster_id}/diff")
def roster_diff(roster_id: int, base_version_id: int | None = None, other_version_id: int | None = None,
                db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """What a revision changed. Defaults to the latest two versions."""
    r = _roster(db, sc, roster_id, Role.VIEWER)
    versions = sorted(r.versions, key=lambda v: v.version_number)
    if len(versions) < 2 and not (base_version_id and other_version_id):
        raise HTTPException(409, "There is only one version, so there is nothing to compare")
    base = _version(db, sc, r, base_version_id) if base_version_id else versions[-2]
    other = _version(db, sc, r, other_version_id) if other_version_id else versions[-1]
    return rp.diff(db, r, base, other)


# ---------------- duty patterns (step 3) ----------------
@router.get("/duty-patterns")
def list_patterns(db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    rows = (sc.filter(db.query(DutyPattern), DutyPattern.cost_center_id)
            .order_by(DutyPattern.pattern_code).all())
    return [dp.pattern_out(p) for p in rows]


@router.post("/duty-patterns", status_code=201)
def create_pattern(body: S.PatternIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    cc = sc.target(Role.SCHEDULER)
    p = DutyPattern(cost_center_id=cc, **body.model_dump())
    db.add(p)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A pattern with this code already exists")
    audit_service.record(db, sc.user, "CREATE", "DutyPattern", p.pattern_id, body.model_dump())
    db.commit()
    return dp.pattern_out(p)


def _pattern(db: Session, sc: Scope, pattern_id: int, minimum: str) -> DutyPattern:
    p = db.get(DutyPattern, pattern_id)
    if p is None:
        raise HTTPException(404, "Pattern not found")
    sc.require(p.cost_center_id, minimum, "Pattern")
    return p


@router.put("/duty-patterns/{pattern_id}")
def update_pattern(pattern_id: int, body: S.PatternIn, db: Session = Depends(get_db),
                   sc: Scope = Depends(scope)):
    p = _pattern(db, sc, pattern_id, Role.SCHEDULER)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    audit_service.record(db, sc.user, "UPDATE", "DutyPattern", pattern_id, body.model_dump())
    db.commit()
    return dp.pattern_out(p)


@router.put("/duty-patterns/{pattern_id}/slots")
def set_pattern_slots(pattern_id: int, body: S.PatternSlotsIn, db: Session = Depends(get_db),
                      sc: Scope = Depends(scope)):
    p = _pattern(db, sc, pattern_id, Role.SCHEDULER)
    dp.set_slots(db, p.cost_center_id, p, body.slots)
    audit_service.record(db, sc.user, "UPDATE", "DutyPattern", pattern_id, {"slots": len(body.slots)})
    db.commit()
    return dp.pattern_out(p)


@router.put("/duty-patterns/{pattern_id}/members")
def set_pattern_members(pattern_id: int, body: S.PatternMembersIn, db: Session = Depends(get_db),
                        sc: Scope = Depends(scope)):
    p = _pattern(db, sc, pattern_id, Role.SCHEDULER)
    dp.set_members(db, p.cost_center_id, p, body.employee_ids)
    audit_service.record(db, sc.user, "UPDATE", "DutyPattern", pattern_id,
                         {"members": len(body.employee_ids)})
    db.commit()
    return dp.pattern_out(p)


@router.delete("/duty-patterns/{pattern_id}", status_code=204)
def delete_pattern(pattern_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    p = _pattern(db, sc, pattern_id, Role.SCHEDULER)
    audit_service.record(db, sc.user, "DELETE", "DutyPattern", pattern_id,
                         {"pattern_code": p.pattern_code})
    db.delete(p)
    db.commit()
    return Response(status_code=204)


@router.get("/duty-patterns/{pattern_id}/preview")
def preview_pattern(pattern_id: int, date_from: dt.date, date_to: dt.date,
                    anchor: dt.date | None = None, db: Session = Depends(get_db),
                    sc: Scope = Depends(scope)):
    """Who the rotation would put where, without writing anything."""
    p = _pattern(db, sc, pattern_id, Role.VIEWER)
    return {"pattern_code": p.pattern_code,
            "rows": dp.preview(p, anchor or date_from, date_from, date_to)}


@router.post("/rosters/{roster_id}/generate")
def generate_roster(roster_id: int, body: S.GenerateIn, db: Session = Depends(get_db),
                    sc: Scope = Depends(scope)):
    """Fill the draft from a duty pattern."""
    r, v = _draft(db, sc, roster_id)
    p = _pattern(db, sc, body.pattern_id, Role.VIEWER)
    if p.cost_center_id != r.cost_center_id:
        raise HTTPException(422, "That pattern belongs to another cost center")
    result = dp.generate(db, r, v, p, body.anchor, body.date_from, body.date_to, body.overwrite)
    audit_service.record(db, sc.user, "GENERATE", "DutyRosterVersion", v.roster_version_id, result)
    db.commit()
    return result | roster_service.grid(db, r, v)


# ---------------- what actually happened (step 5) ----------------
@router.get("/rosters/{roster_id}/actuals")
def actuals_board(roster_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """Every day of the period with its state: open, changed, uncovered, closed."""
    r = _roster(db, sc, roster_id, Role.VIEWER)
    return da.board(db, r)


@router.get("/rosters/{roster_id}/actuals/{on}")
def actuals_day(roster_id: int, on: dt.date, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """One day's plan beside what happened."""
    r = _roster(db, sc, roster_id, Role.VIEWER)
    return da.day_view(db, r, on)


@router.get("/rosters/{roster_id}/actuals/{on}/validate")
def validate_actuals_day(roster_id: int, on: dt.date, db: Session = Depends(get_db),
                         sc: Scope = Depends(scope)):
    """Check what was recorded for a day: nobody in two places at once, everybody fit to be there."""
    r = _roster(db, sc, roster_id, Role.VIEWER)
    return da.validate_day(db, r, on)


@router.post("/rosters/{roster_id}/actuals/open")
def open_duty_day(roster_id: int, body: S.OpenDayIn, db: Session = Depends(get_db),
                  sc: Scope = Depends(scope)):
    """Snapshot the live plan for a day so what happened can be recorded against it."""
    r = _roster(db, sc, roster_id, Role.MIS)
    result = da.open_day(db, r, body.duty_date, sc.user)
    audit_service.record(db, sc.user, "OPEN", "DutyActual", r.roster_id, result)
    db.commit()
    return result | da.day_view(db, r, body.duty_date)


@router.put("/rosters/{roster_id}/actuals/{actual_id}")
def record_duty(roster_id: int, actual_id: int, body: S.DutyActualIn, db: Session = Depends(get_db),
                sc: Scope = Depends(scope)):
    """Record who really worked one duty slot."""
    r = _roster(db, sc, roster_id, Role.MIS)
    x = db.get(DutyActual, actual_id)
    if x is None or x.roster_id != r.roster_id:
        raise HTTPException(404, "Duty not found on this roster")
    da.record(db, r, x, body.status, body.actual_employee_id, body.reason_id, body.remarks, sc.user)
    audit_service.record(db, sc.user, "UPDATE", "DutyActual", actual_id, body.model_dump())
    db.commit()
    return da.day_view(db, r, x.duty_date)


@router.post("/rosters/{roster_id}/actuals/{actual_id}/handover", status_code=201)
def hand_over_duty(roster_id: int, actual_id: int, body: S.DutyHandoverIn, db: Session = Depends(get_db),
                   sc: Scope = Depends(scope)):
    """Split a duty: the driver stops at a time, and whoever took over finishes it."""
    r = _roster(db, sc, roster_id, Role.MIS)
    x = db.get(DutyActual, actual_id)
    if x is None or x.roster_id != r.roster_id:
        raise HTTPException(404, "Duty not found on this roster")
    result = da.handover(db, r, x, body.at_day_offset, body.at_time, body.employee_id,
                         body.reason_id, body.handover_reason, sc.user)
    audit_service.record(db, sc.user, "HANDOVER", "DutyActual", actual_id,
                         body.model_dump(mode="json") | result)
    db.commit()
    return result | da.day_view(db, r, x.duty_date)


@router.delete("/rosters/{roster_id}/actuals/{actual_id}/handover")
def undo_handover(roster_id: int, actual_id: int, db: Session = Depends(get_db),
                  sc: Scope = Depends(scope)):
    """Remove a handover keyed by mistake: the duty goes back to whoever held it before."""
    r = _roster(db, sc, roster_id, Role.MIS)
    x = db.get(DutyActual, actual_id)
    if x is None or x.roster_id != r.roster_id:
        raise HTTPException(404, "Duty not found on this roster")
    day = x.duty_date
    result = da.undo_handover(db, r, x, sc.user)
    audit_service.record(db, sc.user, "UNDO_HANDOVER", "DutyActual", actual_id, result)
    db.commit()
    return result | da.day_view(db, r, day)


@router.post("/rosters/{roster_id}/actuals/close")
def close_duty_day(roster_id: int, body: S.CloseDayIn, db: Session = Depends(get_db),
                   sc: Scope = Depends(scope)):
    """Close the day: its record is frozen and no version may change it again."""
    r = _roster(db, sc, roster_id, Role.PUBLISHER)
    result = da.close_day(db, r, body.duty_date, sc.user, body.force)
    audit_service.record(db, sc.user, "CLOSE", "DutyRoster", r.roster_id, result)
    db.commit()
    return result | da.day_view(db, r, body.duty_date)


@router.post("/rosters/{roster_id}/actuals/reopen")
def reopen_duty_day(roster_id: int, body: S.ReopenDayIn, db: Session = Depends(get_db),
                    sc: Scope = Depends(scope)):
    """Unlock a closed day to correct it. Needs a reason, and unlocks every later day too."""
    r = _roster(db, sc, roster_id, Role.PUBLISHER)
    result = da.reopen_day(db, r, body.duty_date, sc.user, body.reason)
    audit_service.record(db, sc.user, "REOPEN", "DutyRoster", r.roster_id, result)
    db.commit()
    return result | da.day_view(db, r, body.duty_date)
