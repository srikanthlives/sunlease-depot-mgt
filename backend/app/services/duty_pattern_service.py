"""Duty patterns: a repeating crew cycle that generates a draft roster.

A pattern is a rotation. The cycle has `cycle_days` days; each day of the cycle either carries a
duty (a schedule, optionally a shift, and a role) or is an off day. The members are a line of
employees, and each one starts the cycle a day further along: on any date, member *i* works the
duty of cycle day `(days_since_anchor + i) mod cycle_days`. Over a full cycle everybody has
worked every duty and taken every off day, which is what a depot's turn roster does on paper.

Generated assignments are marked `GENERATED` so later hand edits stay visible as `MANUAL`.
"""
import datetime as dt

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.enums import CrewRole, DutySource
from app.models.models import (
    BusSchedule, DutyPattern, DutyPatternMember, DutyPatternSlot, DutyRoster, DutyRosterVersion,
    Employee,
)
from app.services import roster_service


def bad(status: int, msg: str):
    raise HTTPException(status, msg)


def _check_slots(pattern: DutyPattern, slots) -> None:
    """One duty per cycle day: the rotation gives each member exactly one line through the cycle,
    so two duties on the same cycle day would put one member on two buses at once. A depot that
    needs a second duty on that day builds a second pattern."""
    seen = set()
    for s in slots:
        if not (0 <= s.cycle_day < pattern.cycle_days):
            bad(422, f"Cycle day {s.cycle_day} is outside a {pattern.cycle_days}-day cycle "
                     f"(use 0 to {pattern.cycle_days - 1})")
        if s.cycle_day in seen:
            bad(422, f"Cycle day {s.cycle_day} already has a duty. One duty per cycle day: "
                     "add a second pattern for another line of crew")
        seen.add(s.cycle_day)


def set_slots(db: Session, roster_cc: int, pattern: DutyPattern, slots_in) -> DutyPattern:
    """Replace the cycle's duties. `schedule_id` empty means an off day."""
    rows = []
    for s in slots_in:
        if s.schedule_id is not None:
            sch = db.get(BusSchedule, s.schedule_id)
            if sch is None or sch.cost_center_id != roster_cc:
                bad(422, f"Schedule {s.schedule_id} does not exist in this cost center")
        rows.append(DutyPatternSlot(pattern_id=pattern.pattern_id, cycle_day=s.cycle_day,
                                    schedule_id=s.schedule_id, shift_number=s.shift_number,
                                    crew_role=s.crew_role))
    _check_slots(pattern, rows)
    pattern.slots.clear()
    db.flush()
    for r in rows:
        pattern.slots.append(r)
    db.flush()
    return pattern


def set_members(db: Session, cost_center_id: int, pattern: DutyPattern, employee_ids) -> DutyPattern:
    """The line of crew, in rotation order. More members than cycle days would put two of them on
    the same duty on the same date, so the line cannot be longer than the cycle."""
    if len(employee_ids) > pattern.cycle_days:
        bad(422, f"{len(employee_ids)} members in a {pattern.cycle_days}-day cycle: the line "
                 "cannot be longer than the cycle, or two of them land on the same duty")
    if len(set(employee_ids)) != len(employee_ids):
        bad(422, "The same employee appears twice in the line")
    members = []
    for order, employee_id in enumerate(employee_ids):
        e = db.get(Employee, employee_id)
        if e is None or e.cost_center_id != cost_center_id:
            bad(422, f"Employee {employee_id} does not exist in this cost center")
        members.append(DutyPatternMember(pattern_id=pattern.pattern_id, employee_id=employee_id,
                                         member_order=order))
    pattern.members.clear()
    db.flush()
    for m in members:
        pattern.members.append(m)
    db.flush()
    return pattern


def preview(pattern: DutyPattern, anchor: dt.date, date_from: dt.date, date_to: dt.date) -> list[dict]:
    """Who the rotation puts where, without writing anything."""
    by_day = {s.cycle_day: s for s in pattern.slots}
    out = []
    day = date_from
    while day <= date_to:
        offset = (day - anchor).days
        for m in sorted(pattern.members, key=lambda x: x.member_order):
            slot = by_day.get((offset + m.member_order) % pattern.cycle_days)
            out.append({
                "duty_date": day.isoformat(), "employee_id": m.employee_id,
                "employee_number": m.employee.employee_number,
                "employee_name": m.employee.full_name,
                "cycle_day": (offset + m.member_order) % pattern.cycle_days,
                "schedule_id": slot.schedule_id if slot else None,
                "schedule_code": slot.schedule.schedule_code if slot and slot.schedule else None,
                "shift_number": slot.shift_number if slot else None,
                "crew_role": slot.crew_role if slot else None,
                "off": slot is None or slot.schedule_id is None,
            })
        day += dt.timedelta(days=1)
    return out


def generate(db: Session, roster: DutyRoster, version: DutyRosterVersion, pattern: DutyPattern,
             anchor: dt.date | None = None, date_from: dt.date | None = None,
             date_to: dt.date | None = None, overwrite: bool = False) -> dict:
    """Write the rotation into the draft.

    Days the schedule does not run, and days already closed, are skipped rather than forced.
    Cells a person filled by hand are kept unless `overwrite` is asked for, so a generated
    roster can be re-generated without losing the depot's own corrections.
    """
    roster_service.assert_draft(version)
    if not pattern.slots:
        bad(422, "The pattern has no duties in its cycle yet")
    if not pattern.members:
        bad(422, "The pattern has nobody in its line yet")

    start = date_from or roster.period_from
    end = date_to or roster.period_to
    if start < roster.period_from or end > roster.period_to:
        bad(422, "The dates to generate must lie inside the roster period")
    base = anchor or roster.period_from

    existing = {}
    for a in version.assignments:
        shift_number = a.shift.shift_number if a.shift else None
        existing[(a.duty_date, a.schedule_id, shift_number, a.crew_role)] = a

    written = skipped_closed = skipped_not_running = kept_manual = off_days = 0
    for row in preview(pattern, base, start, end):
        day = dt.date.fromisoformat(row["duty_date"])
        if row["off"]:
            off_days += 1
            continue
        if roster.locked_through and day <= roster.locked_through:
            skipped_closed += 1
            continue
        key = (day, row["schedule_id"], row["shift_number"], row["crew_role"])
        current = existing.get(key)
        if current is not None and current.source == DutySource.MANUAL and current.employee_id \
                and not overwrite:
            kept_manual += 1
            continue
        sch = db.get(BusSchedule, row["schedule_id"])
        if not any(s.key == (row["schedule_id"], row["shift_number"], row["crew_role"])
                   for s in roster_service.slots_for_date([sch], day)):
            skipped_not_running += 1
            continue
        roster_service.set_assignment(db, roster, version, day, row["schedule_id"],
                                      row["shift_number"], row["crew_role"], row["employee_id"],
                                      source=DutySource.GENERATED)
        written += 1

    return {"pattern_code": pattern.pattern_code, "written": written, "off_days": off_days,
            "kept_manual": kept_manual, "skipped_closed": skipped_closed,
            "skipped_not_running": skipped_not_running,
            "anchor": base.isoformat(), "date_from": start.isoformat(), "date_to": end.isoformat()}


def pattern_out(p: DutyPattern) -> dict:
    return {
        "pattern_id": p.pattern_id, "cost_center_id": p.cost_center_id,
        "pattern_code": p.pattern_code, "pattern_name": p.pattern_name,
        "cycle_days": p.cycle_days, "is_active": p.is_active,
        "slots": [{"slot_id": s.slot_id, "cycle_day": s.cycle_day, "schedule_id": s.schedule_id,
                   "schedule_code": s.schedule.schedule_code if s.schedule else None,
                   "shift_number": s.shift_number, "crew_role": s.crew_role,
                   "off": s.schedule_id is None}
                  for s in sorted(p.slots, key=lambda s: s.cycle_day)],
        "members": [{"member_id": m.member_id, "member_order": m.member_order,
                     "employee_id": m.employee_id,
                     "employee_number": m.employee.employee_number if m.employee else None,
                     "employee_name": m.employee.full_name if m.employee else None}
                    for m in sorted(p.members, key=lambda m: m.member_order)],
    }
