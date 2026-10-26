"""What really happened in each duty slot, day by day.

The plan is never touched by this. Opening a day snapshots the live version's duties into
`duty_actuals` rows, and the clerk then records who actually worked each one. The rows are keyed
on the ROSTER rather than a version, so publishing a revision slides underneath what has already
been recorded instead of orphaning or duplicating it.

Closing a day locks its rows (the database enforces it) and advances the roster's
`locked_through`, which is also what stops any later version from changing a completed day.
"""
import datetime as dt

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.enums import DutyActualStatus
from app.models.models import DutyActual, DutyRoster, Employee, TripReason, TripSheet
from app.services import availability_service, roster_service
from app.services.schedule_service import cycle_span, shift_span, version_for_date


def bad(status: int, msg: str):
    raise HTTPException(status, msg)


SCHEDULE = "SCHEDULE"


def roster_for_date(db: Session, cost_center_ids, on: dt.date) -> DutyRoster | None:
    return (db.query(DutyRoster)
            .filter(DutyRoster.cost_center_id.in_(cost_center_ids),
                    DutyRoster.period_from <= on, DutyRoster.period_to >= on)
            .first())


def _key(x: DutyActual):
    return (x.duty_type, x.schedule_id, x.shift_id, x.crew_role, x.slot_index)


def open_day(db: Session, roster: DutyRoster, day: dt.date, user) -> dict:
    """Snapshot the live plan for one day so the actuals can be recorded against it.

    Run again later, it adds slots that have appeared since (a revised schedule, a new spare)
    and leaves everything already recorded alone.
    """
    if not (roster.period_from <= day <= roster.period_to):
        bad(422, f"{day:%d-%b-%Y} is outside the roster period")
    if roster.locked_through and day <= roster.locked_through:
        bad(409, f"{day:%d-%b-%Y} is closed")
    live = roster_service.live_version(roster)
    if live is None:
        bad(409, "Publish the roster before recording what happened")

    existing = {_key(x): x for x in db.query(DutyActual).filter(
        DutyActual.roster_id == roster.roster_id, DutyActual.duty_date == day).all()}

    def hours(a) -> dict:
        """The duty's planned hours, so a handover has something to split."""
        if a.shift is not None:
            return {"duty_start_day_offset": a.shift.start_day_offset,
                    "duty_start_time": a.shift.start_time,
                    "duty_end_day_offset": a.shift.end_day_offset,
                    "duty_end_time": a.shift.end_time}
        version = version_for_date(a.schedule, day) if a.schedule else None
        span = cycle_span(version) if version else None
        if span is None:
            return {}
        return {"duty_start_day_offset": span[0] // 1440,
                "duty_start_time": dt.time((span[0] % 1440) // 60, span[0] % 60),
                "duty_end_day_offset": span[1] // 1440,
                "duty_end_time": dt.time((span[1] % 1440) // 60, span[1] % 60)}

    added = 0  # noqa: E501
    for a in live.assignments:
        if a.duty_date != day:
            continue
        key = (SCHEDULE, a.schedule_id, a.shift_id, a.crew_role, 0)
        if key in existing:
            continue
        db.add(DutyActual(roster_id=roster.roster_id, duty_date=day, duty_type=SCHEDULE,
                          schedule_id=a.schedule_id, shift_id=a.shift_id, slot_index=0,
                          crew_role=a.crew_role, planned_employee_id=a.employee_id,
                          actual_employee_id=a.employee_id,
                          status=DutyActualStatus.AS_PLANNED,
                          roster_version_id=live.roster_version_id, **hours(a)))
        added += 1
    for x in live.extras:
        if x.duty_date != day:
            continue
        key = (x.duty_type, None, None, x.crew_role, x.slot_index)
        if key in existing:
            continue
        db.add(DutyActual(roster_id=roster.roster_id, duty_date=day, duty_type=x.duty_type,
                          schedule_id=None, shift_id=None, slot_index=x.slot_index,
                          crew_role=x.crew_role, planned_employee_id=x.employee_id,
                          actual_employee_id=x.employee_id,
                          duty_start_day_offset=0 if x.start_time else None,
                          duty_start_time=x.start_time,
                          duty_end_day_offset=0 if x.end_time else None,
                          duty_end_time=x.end_time,
                          status=DutyActualStatus.AS_PLANNED,
                          roster_version_id=live.roster_version_id))
        added += 1
    db.flush()
    return {"duty_date": day.isoformat(), "opened": added,
            "already_open": len(existing), "roster_version_id": live.roster_version_id}


def record(db: Session, roster: DutyRoster, x: DutyActual, status: str,
           actual_employee_id: int | None, reason_id: int | None, remarks: str | None, user) -> DutyActual:
    """Record one slot. The status follows from who worked it, so it is derived rather than
    trusted: a different person is a replacement, nobody is an absence."""
    if roster.locked_through and x.duty_date <= roster.locked_through:
        bad(409, f"{x.duty_date:%d-%b-%Y} is closed: reopen the day to change it")
    if actual_employee_id is not None:
        e = db.get(Employee, actual_employee_id)
        if e is None or e.cost_center_id != roster.cost_center_id:
            bad(422, f"Employee {actual_employee_id} does not exist in this cost center")
        if e.staff_type != x.crew_role:
            bad(422, f"{e.full_name} is a {e.staff_type.lower().replace('_', ' ')}, "
                     f"not a {x.crew_role.lower()}")
    if reason_id is not None and db.get(TripReason, reason_id) is None:
        bad(422, "Unknown reason code")

    handed_over = db.query(DutyActual).filter(DutyActual.replaces_actual_id == x.actual_id).count()
    if status == DutyActualStatus.NOT_OPERATED:
        actual_employee_id = None
    elif actual_employee_id is None:
        status = DutyActualStatus.ABSENT
    elif x.replaces_actual_id is not None:
        status = DutyActualStatus.TOOK_OVER      # a segment picked up mid-duty stays that
    elif handed_over:
        status = DutyActualStatus.HANDED_OVER    # this segment was given up part-way
    elif actual_employee_id == x.planned_employee_id:
        status = DutyActualStatus.AS_PLANNED
    else:
        status = DutyActualStatus.REPLACED

    if status != DutyActualStatus.AS_PLANNED and reason_id is None and not remarks:
        bad(422, "A change from the plan needs a reason code or a remark")

    x.status = status
    x.actual_employee_id = actual_employee_id
    x.reason_id = reason_id
    x.remarks = remarks
    x.recorded_by = user.id
    x.recorded_at = dt.datetime.utcnow()
    return x


def _rel(offset, time) -> int | None:
    """Minutes from the start of the duty's first day."""
    if time is None:
        return None
    return (offset or 0) * 1440 + time.hour * 60 + time.minute


def _segments(db: Session, x: DutyActual) -> list[DutyActual]:
    """Every segment of the duty slot `x` belongs to, in order."""
    return (db.query(DutyActual)
            .filter(DutyActual.roster_id == x.roster_id, DutyActual.duty_date == x.duty_date,
                    DutyActual.duty_type == x.duty_type, DutyActual.schedule_id == x.schedule_id,
                    DutyActual.shift_id == x.shift_id, DutyActual.crew_role == x.crew_role,
                    DutyActual.slot_index == x.slot_index)
            .order_by(DutyActual.segment).all())


def handover(db: Session, roster: DutyRoster, x: DutyActual, at_day_offset: int, at_time: dt.time,
             employee_id: int | None, reason_id: int | None, handover_reason: str | None,
             user) -> dict:
    """The driver stops part-way and somebody else finishes the duty.

    The segment being handed over ends at `at`, and a new segment starts there for whoever took
    it on - the same shape a trip sheet's crew change uses. The reason belongs to the segment
    that ended, because it says why that person stopped.
    """
    if roster.locked_through and x.duty_date <= roster.locked_through:
        bad(409, f"{x.duty_date:%d-%b-%Y} is closed: reopen the day to change it")
    if x.status in (DutyActualStatus.NOT_OPERATED, DutyActualStatus.ABSENT):
        bad(409, "That duty was not worked, so there is nothing to hand over")
    if db.query(DutyActual).filter(DutyActual.replaces_actual_id == x.actual_id).count():
        bad(409, "That segment was already handed over: hand over the last segment instead")
    if x.actual_employee_id is None:
        bad(422, "Record who was working the duty before handing it over")

    if x.duty_start_time is None or x.duty_end_time is None:
        for field, value in planned_hours(x).items():     # a row recorded before hours were kept
            setattr(x, field, value)
    start, end = _rel(x.duty_start_day_offset, x.duty_start_time), _rel(x.duty_end_day_offset, x.duty_end_time)
    at = _rel(at_day_offset, at_time)
    if start is None or end is None:
        bad(409, "This duty has no hours recorded, so it cannot be split at a time")
    if not (start < at < end):
        bad(422, f"The change time must fall inside the duty "
                 f"({x.duty_start_time:%H:%M} to {x.duty_end_time:%H:%M})")
    if not reason_id and not (handover_reason or "").strip():
        bad(422, "A handover needs a reason code or a remark saying why the driver stopped")
    if employee_id is not None:
        e = db.get(Employee, employee_id)
        if e is None or e.cost_center_id != roster.cost_center_id:
            bad(422, f"Employee {employee_id} does not exist in this cost center")
        if e.staff_type != x.crew_role:
            bad(422, f"{e.full_name} is a {e.staff_type.lower().replace('_', ' ')}, "
                     f"not a {x.crew_role.lower()}")
    if reason_id is not None and db.get(TripReason, reason_id) is None:
        bad(422, "Unknown reason code")

    segments = _segments(db, x)
    taking_over = DutyActual(
        roster_id=x.roster_id, duty_date=x.duty_date, duty_type=x.duty_type,
        schedule_id=x.schedule_id, shift_id=x.shift_id, slot_index=x.slot_index,
        segment=max(s.segment for s in segments) + 1, crew_role=x.crew_role,
        planned_employee_id=x.planned_employee_id,      # the slot's own crew, for reporting
        actual_employee_id=employee_id,
        duty_start_day_offset=at_day_offset, duty_start_time=at_time,
        duty_end_day_offset=x.duty_end_day_offset, duty_end_time=x.duty_end_time,
        replaces_actual_id=x.actual_id, reason_id=reason_id,
        status=(DutyActualStatus.TOOK_OVER if employee_id is not None
                else DutyActualStatus.NOT_OPERATED),
        roster_version_id=x.roster_version_id, recorded_by=user.id, recorded_at=dt.datetime.utcnow())
    db.add(taking_over)

    x.duty_end_day_offset, x.duty_end_time = at_day_offset, at_time
    x.status = DutyActualStatus.HANDED_OVER
    x.reason_id = reason_id or x.reason_id
    x.handover_reason = handover_reason
    x.recorded_by, x.recorded_at = user.id, dt.datetime.utcnow()
    db.flush()
    return {"handed_over": x.actual_id, "took_over": taking_over.actual_id,
            "at": f"{at_time:%H:%M}" + (f" +{at_day_offset}" if at_day_offset else "")}


def undo_handover(db: Session, roster: DutyRoster, x: DutyActual, user) -> dict:
    """Remove the last segment and give the duty back to whoever held it before.

    A handover keyed by mistake has to be undoable, and a segment is not something the clerk
    can simply edit away.
    """
    if roster.locked_through and x.duty_date <= roster.locked_through:
        bad(409, f"{x.duty_date:%d-%b-%Y} is closed: reopen the day to change it")
    if x.replaces_actual_id is None:
        bad(409, "That is the first segment of the duty, so there is no handover to undo")
    if db.query(DutyActual).filter(DutyActual.replaces_actual_id == x.actual_id).count():
        bad(409, "A later segment took over from this one: undo that first")

    previous = db.get(DutyActual, x.replaces_actual_id)
    previous.duty_end_day_offset, previous.duty_end_time = x.duty_end_day_offset, x.duty_end_time
    previous.handover_reason = None
    if previous.replaces_actual_id is not None:
        previous.status = DutyActualStatus.TOOK_OVER     # a middle segment is still a takeover
    elif previous.actual_employee_id is None:
        previous.status = DutyActualStatus.ABSENT
    elif previous.actual_employee_id == previous.planned_employee_id:
        previous.status = DutyActualStatus.AS_PLANNED
    else:
        previous.status = DutyActualStatus.REPLACED
    previous.recorded_by, previous.recorded_at = user.id, dt.datetime.utcnow()
    db.delete(x)
    db.flush()
    return {"removed": x.actual_id, "restored": previous.actual_id, "status": previous.status}


def close_day(db: Session, roster: DutyRoster, day: dt.date, user, force: bool = False) -> dict:
    """Close a day: its actuals are frozen and no version may change it again."""
    if roster.locked_through and day <= roster.locked_through:
        bad(409, f"{day:%d-%b-%Y} is already closed")
    rows = db.query(DutyActual).filter(DutyActual.roster_id == roster.roster_id,
                                       DutyActual.duty_date == day).all()
    if not rows:
        bad(409, f"{day:%d-%b-%Y} was never opened, so there is nothing to close")
    unrecorded = [r for r in rows if r.recorded_at is None
                  and r.status == DutyActualStatus.AS_PLANNED and r.planned_employee_id is None]
    if unrecorded and not force:
        bad(409, f"{len(unrecorded)} slot(s) on {day:%d-%b-%Y} have nobody in them: "
                 "record them, or confirm closing the day as it stands")
    checked = validate_day(db, roster, day)
    if checked["errors"] and not force:
        first = next(i["message"] for i in checked["issues"] if i["severity"] == "ERROR")
        bad(409, f"{checked['errors']} error(s) in the record for {day:%d-%b-%Y}: {first}")
    # closing day N closes everything up to N, so a skipped day cannot be edited afterwards
    roster.locked_through = day if roster.locked_through is None else max(roster.locked_through, day)
    db.flush()
    return {"duty_date": day.isoformat(), "locked_through": roster.locked_through.isoformat(),
            "slots": len(rows), "closed_without_record": len(unrecorded) if force else 0}


def reopen_day(db: Session, roster: DutyRoster, day: dt.date, user, reason: str) -> dict:
    """Reopen a closed day. The same escape hatch trip sheets have: a mistake found after the
    fact has to be correctable, so a publisher may unlock a day by giving a reason.

    Reopening day N unlocks N and everything after it, because `locked_through` is a single
    watermark - days before N stay closed.
    """
    if not reason or not reason.strip():
        bad(422, "Reopening a closed day needs a reason")
    if roster.locked_through is None or day > roster.locked_through:
        bad(409, f"{day:%d-%b-%Y} is not closed")
    before = roster.locked_through
    previous = day - dt.timedelta(days=1)
    roster.locked_through = None if previous < roster.period_from else previous
    db.flush()
    return {"duty_date": day.isoformat(), "was_locked_through": before.isoformat(),
            "locked_through": roster.locked_through.isoformat() if roster.locked_through else None,
            "reason": reason}


# --------------------------------------------------------------------------
# Planned against actual
# --------------------------------------------------------------------------
def _person(e: Employee | None) -> dict | None:
    if e is None:
        return None
    return {"employee_id": e.employee_id, "employee_number": e.employee_number,
            "employee_name": e.full_name}


def _label(x: DutyActual) -> tuple[str, str]:
    if x.duty_type != SCHEDULE:
        return x.duty_type.title(), f"{x.duty_type.title()} {x.slot_index}"
    code = x.schedule.schedule_code if x.schedule else "?"
    slot = x.crew_role.title() + (f" - {x.shift.shift_name}" if x.shift else "")
    return code, slot


def day_view(db: Session, roster: DutyRoster, day: dt.date) -> dict:
    """One day's plan beside what happened, which is what the comparison screen shows."""
    rows = (db.query(DutyActual)
            .filter(DutyActual.roster_id == roster.roster_id, DutyActual.duty_date == day)
            .order_by(DutyActual.duty_type, DutyActual.schedule_id, DutyActual.slot_index).all())
    counts = {s: 0 for s in DutyActualStatus.ALL}
    covered_by = {}
    for x in rows:
        if x.duty_type == SCHEDULE and x.actual_employee_id is not None \
                and x.actual_employee_id != x.planned_employee_id:
            covered_by.setdefault(x.actual_employee_id, _label(x)[0])
    items = []
    for x in rows:
        counts[x.status] = counts.get(x.status, 0) + 1
        code, slot = _label(x)
        span = _actual_span(x)
        hrs = _hours_of(x)
        items.append({
            "actual_id": x.actual_id, "duty_type": x.duty_type, "schedule_code": code,
            "fleet_number": x.schedule.vehicle.fleet_number if x.schedule else None,
            "slot_label": slot, "crew_role": x.crew_role,
            # which stretch of the duty this row is, and the hours it covers
            "segment": x.segment,
            "segments": sum(1 for o in rows if (o.duty_type, o.schedule_id, o.shift_id,
                                                o.crew_role, o.slot_index)
                            == (x.duty_type, x.schedule_id, x.shift_id, x.crew_role, x.slot_index)),
            "from_time": (hrs.get("duty_start_time").strftime("%H:%M")
                          if hrs.get("duty_start_time") else None),
            "to_time": (hrs.get("duty_end_time").strftime("%H:%M")
                        if hrs.get("duty_end_time") else None),
            "minutes": (span[1] - span[0]) if span else None,
            "took_over_from": x.replaces_actual_id,
            "handover_reason": x.handover_reason,
            "planned": _person(x.planned_employee), "actual": _person(x.actual_employee),
            "status": x.status, "reason_id": x.reason_id,
            "reason": x.reason.reason_name if x.reason else None,
            "remarks": x.remarks, "recorded_at": x.recorded_at,
            # a spare who was called out says where to, instead of just "on standby"
            "called_out_to": (covered_by.get(x.actual_employee_id)
                              if x.duty_type == "SPARE" else None),
        })
    return {"roster_id": roster.roster_id, "duty_date": day.isoformat(),
            "locked": bool(roster.locked_through and day <= roster.locked_through),
            "open": bool(rows), "counts": counts, "slots": len(rows), "rows": items,
            "validation": validate_day(db, roster, day) if rows else None}


def planned_hours(x: DutyActual) -> dict:
    """The hours the duty is planned to run, worked out from the shift or the schedule's cycle.

    Rows recorded before the hours were stored have none, so they are derived on demand - that
    way an older day can still be handed over without a backfill.
    """
    if x.duty_type != SCHEDULE:
        return {}
    if x.shift is not None:
        return {"duty_start_day_offset": x.shift.start_day_offset,
                "duty_start_time": x.shift.start_time,
                "duty_end_day_offset": x.shift.end_day_offset,
                "duty_end_time": x.shift.end_time}
    version = version_for_date(x.schedule, x.duty_date) if x.schedule else None
    span = cycle_span(version) if version else None
    if span is None:
        return {}
    return {"duty_start_day_offset": span[0] // 1440,
            "duty_start_time": dt.time((span[0] % 1440) // 60, span[0] % 60),
            "duty_end_day_offset": span[1] // 1440,
            "duty_end_time": dt.time((span[1] % 1440) // 60, span[1] % 60)}


def _hours_of(x: DutyActual) -> dict:
    """What this row holds, falling back on the plan."""
    if x.duty_start_time is not None and x.duty_end_time is not None:
        return {"duty_start_day_offset": x.duty_start_day_offset, "duty_start_time": x.duty_start_time,
                "duty_end_day_offset": x.duty_end_day_offset, "duty_end_time": x.duty_end_time}
    return planned_hours(x)


def _actual_span(x: DutyActual) -> tuple[int, int] | None:
    """The minutes this person actually held, measured from the start of the duty's first day.

    The recorded hours are used when there are any, so a duty handed over at 11:20 counts as
    two shorter stretches rather than two whole days. Falling back on the plan keeps older
    records, entered before the hours were snapshotted, checkable.

    A spare is standby, not a span: being on call cannot clash with anything, so it is
    reported separately.
    """
    if x.duty_type == "SPARE":
        return None
    start, end = _rel(x.duty_start_day_offset, x.duty_start_time), _rel(x.duty_end_day_offset, x.duty_end_time)
    if start is not None and end is not None and end > start:
        return (start, end)
    if x.duty_type == SCHEDULE:
        if x.shift is not None:
            return shift_span(x.shift)
        if x.schedule is None:
            return None
        version = version_for_date(x.schedule, x.duty_date)
        return cycle_span(version) if version else None
    return None


def validate_day(db: Session, roster: DutyRoster, day: dt.date) -> dict:
    """Check the recorded day: nobody in two places at once, and everybody fit to be there.

    This is the plan's own validation applied to what happened. It matters most for a
    replacement: the clerk knows who turned up for the bus in front of them, not what that
    person was already down for elsewhere in the depot.
    """
    rows = (db.query(DutyActual)
            .filter(DutyActual.roster_id == roster.roster_id, DutyActual.duty_date == day)
            .order_by(DutyActual.duty_type, DutyActual.schedule_id, DutyActual.slot_index).all())
    iss = roster_service.Issues()
    worked: dict[int, list[tuple[tuple[int, int] | None, DutyActual]]] = {}

    # who covered a duty they were not planned for: for a spare that is the whole point
    covered = {x.actual_employee_id for x in rows
               if x.duty_type == SCHEDULE and x.actual_employee_id is not None
               and x.actual_employee_id != x.planned_employee_id}

    for x in rows:
        code, slot = _label(x)
        where = {"day": day, "schedule_code": code, "slot": slot}
        if x.status == DutyActualStatus.ABSENT:
            iss.warn("ACTUAL_UNCOVERED", f"{code} {slot} on {day:%d-%b-%Y}: nobody worked it", **where)
            continue
        if x.status == DutyActualStatus.NOT_OPERATED:
            continue
        if x.actual_employee_id is None:
            iss.warn("ACTUAL_EMPTY", f"{code} {slot} on {day:%d-%b-%Y}: nobody recorded yet", **where)
            continue
        if x.recorded_at is None and x.planned_employee_id is None:
            iss.warn("ACTUAL_EMPTY", f"{code} {slot} on {day:%d-%b-%Y}: not confirmed yet", **where)

        e = x.actual_employee
        if e.staff_type != x.crew_role:
            iss.error("ACTUAL_TYPE", f"{e.full_name} is a {e.staff_type.lower().replace('_', ' ')}, "
                                     f"not a {x.crew_role.lower()}", **where)
        if not availability_service.employed_on(e, day):
            iss.error("ACTUAL_DATES", f"{e.full_name} was not on the rolls on {day:%d-%b-%Y}", **where)
        entry = availability_service.unavailable_on(db, e.employee_id, day)
        if entry is not None:
            iss.warn("ACTUAL_UNAVAILABLE", f"{e.full_name} is marked "
                                           f"{entry.status.replace('_', ' ').lower()} on "
                                           f"{day:%d-%b-%Y} but worked {code} {slot}", **where)
        worked.setdefault(e.employee_id, []).append((_actual_span(x), x))

    for employee_id, duties in worked.items():
        if len(duties) < 2:
            continue
        name = duties[0][1].actual_employee.full_name
        for i, (span, x) in enumerate(duties):
            for other_span, other in duties[i + 1:]:
                a_code, a_slot = _label(x)
                b_code, b_slot = _label(other)
                where = {"day": day, "schedule_code": a_code, "slot": a_slot}
                if x.duty_type == "SPARE" or other.duty_type == "SPARE":
                    if employee_id in covered:
                        continue        # a spare called out to a duty: that is what spares are for
                    iss.warn("ACTUAL_ALSO_SPARE",
                             f"{name} is recorded as spare and also worked "
                             f"{(b_code if x.duty_type == 'SPARE' else a_code)} on {day:%d-%b-%Y}",
                             **where)
                elif span is None or other_span is None:
                    iss.warn("ACTUAL_SAME_DAY", f"{name} worked {a_code} {a_slot} and {b_code} "
                                                f"{b_slot} on {day:%d-%b-%Y}", **where)
                elif span[0] < other_span[1] and other_span[0] < span[1]:
                    iss.error("ACTUAL_DOUBLE_BOOKED",
                              f"{name} is recorded on {a_code} {a_slot} and {b_code} {b_slot} on "
                              f"{day:%d-%b-%Y}, and the two overlap: one of them is wrong", **where)
                else:
                    iss.warn("ACTUAL_SAME_DAY", f"{name} worked {a_code} {a_slot} and then "
                                                f"{b_code} {b_slot} on {day:%d-%b-%Y}", **where)

    # the segments of one duty must meet, and together cover it
    slots: dict[tuple, list[DutyActual]] = {}
    for x in rows:
        slots.setdefault((x.duty_type, x.schedule_id, x.shift_id, x.crew_role, x.slot_index), []).append(x)
    for parts in slots.values():
        if len(parts) < 2:
            continue
        parts.sort(key=lambda s: s.segment)
        code, _ = _label(parts[0])
        for first, second in zip(parts, parts[1:]):
            where = {"day": day, "schedule_code": code, "slot": _label(second)[1]}
            ends, starts = _rel(first.duty_end_day_offset, first.duty_end_time), \
                _rel(second.duty_start_day_offset, second.duty_start_time)
            if ends is None or starts is None:
                continue
            if starts > ends:
                iss.error("SEGMENT_GAP", f"{code} {_label(second)[1]} on {day:%d-%b-%Y}: nobody is "
                                         f"recorded between {first.duty_end_time:%H:%M} and "
                                         f"{second.duty_start_time:%H:%M}", **where)
            elif starts < ends:
                iss.error("SEGMENT_OVERLAP", f"{code} {_label(second)[1]} on {day:%d-%b-%Y}: the "
                                             f"handover at {second.duty_start_time:%H:%M} is before "
                                             f"{first.duty_end_time:%H:%M}, when the duty was given up",
                          **where)

    out = iss.result()
    out["can_close"] = out["errors"] == 0
    return out


def board(db: Session, roster: DutyRoster) -> dict:
    """Every day of the period with its state, for the strip above the comparison."""
    rows = (db.query(DutyActual)
            .filter(DutyActual.roster_id == roster.roster_id).all())
    per_day: dict[dt.date, list[DutyActual]] = {}
    for x in rows:
        per_day.setdefault(x.duty_date, []).append(x)
    out = []
    for day in roster_service.days_of(roster):
        day_rows = per_day.get(day, [])
        changed = sum(1 for x in day_rows if x.status != DutyActualStatus.AS_PLANNED)
        out.append({"duty_date": day.isoformat(), "weekday": day.strftime("%a"),
                    "open": bool(day_rows), "slots": len(day_rows), "changed": changed,
                    "uncovered": sum(1 for x in day_rows if x.status == DutyActualStatus.ABSENT),
                    "locked": bool(roster.locked_through and day <= roster.locked_through)})
    return {"roster_id": roster.roster_id, "roster_code": roster.roster_code,
            "locked_through": roster.locked_through, "days": out}


def crew_for_sheet(db: Session, sheet: TripSheet) -> dict[tuple, list[int]]:
    """Who the roster has on one bus on one date, per crew slot, used to pre-fill and to check
    a trip sheet's crew.

    Each slot maps to a LIST, in order, because a duty handed over part-way was held by more
    than one person. The recorded actuals win once the day has been opened - by then the depot
    knows who really turned up - and the plan is used otherwise.
    """
    roster = roster_for_date(db, [sheet.cost_center_id], sheet.operating_date)
    if roster is None:
        return {}
    out: dict[tuple, list[int]] = {}
    actuals = (db.query(DutyActual)
               .filter(DutyActual.roster_id == roster.roster_id,
                       DutyActual.duty_date == sheet.operating_date,
                       DutyActual.schedule_id == sheet.schedule_id)
               .order_by(DutyActual.segment).all())
    for x in actuals:
        who = x.actual_employee_id or x.planned_employee_id
        if who is not None and who not in out.setdefault((x.shift_id, x.crew_role), []):
            out[(x.shift_id, x.crew_role)].append(who)
    out = {k: v for k, v in out.items() if v}
    if out:
        return out
    live = roster_service.live_version(roster)
    if live is None:
        return {}
    for a in live.assignments:
        if a.duty_date == sheet.operating_date and a.schedule_id == sheet.schedule_id \
                and a.employee_id is not None:
            out.setdefault((a.shift_id, a.crew_role), []).append(a.employee_id)
    return out
