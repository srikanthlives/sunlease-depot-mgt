"""Duty roster: the draft grid of who is planned to work which bus on which date.

Which schedules run on a date, and which crew slots each needs, is not stored on the
roster: it is read from the schedule version in force on that date (`version_for_date`,
the same authority the missing-sheets report uses). So a roster never goes stale when a
schedule is revised - the grid simply shows the slots that now apply.

Publishing and the version bookkeeping live in `roster_publish_service`; what actually
happened on the day lives in `duty_actual_service`.
"""
import datetime as dt

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.enums import CrewMode, CrewRole, DutySource, DutyType, RosterStatus
from app.models.models import (
    BusSchedule, DutyActual, DutyAssignment, DutyExtra, DutyRoster, DutyRosterVersion, Employee,
    ScheduleShift,
)
from app.services import availability_service
from app.services.schedule_service import cycle_span, shift_span, version_for_date

MAX_PERIOD_DAYS = 366


def _hhmm(minutes: int | None) -> str | None:
    """Minutes from the schedule's day start as HH:MM, with +1 for the next day."""
    if minutes is None:
        return None
    day, rest = divmod(int(minutes), 1440)
    return f"{rest // 60:02d}:{rest % 60:02d}" + (f" +{day}" if day else "")


def bad(status: int, msg: str):
    raise HTTPException(status, msg)


# --------------------------------------------------------------------------
# Rosters and their draft version
# --------------------------------------------------------------------------
def live_version(roster: DutyRoster) -> DutyRosterVersion | None:
    """The one published version everything reads. Earlier ones are kept only to diff."""
    published = [v for v in roster.versions if v.status == RosterStatus.PUBLISHED]
    return max(published, key=lambda v: v.version_number) if published else None


def draft_version(roster: DutyRoster) -> DutyRosterVersion | None:
    for v in roster.versions:
        if v.status == RosterStatus.DRAFT:
            return v
    return None


def assert_draft(version: DutyRosterVersion) -> None:
    if version.status != RosterStatus.DRAFT:
        bad(409, f"Roster version {version.version_number} is {version.status.lower()}: "
                 "create a new version to change it")


def assert_open(roster: DutyRoster, day: dt.date) -> None:
    """A day already closed is history: no version may change it."""
    if roster.locked_through and day <= roster.locked_through:
        bad(409, f"{day:%d-%b-%Y} is closed (the roster is locked through "
                 f"{roster.locked_through:%d-%b-%Y})")


def create_roster(db: Session, cost_center_id: int, code: str, name: str | None,
                  period_from: dt.date, period_to: dt.date, user) -> DutyRoster:
    if period_to < period_from:
        bad(422, "The period's last day cannot be before its first day")
    if (period_to - period_from).days + 1 > MAX_PERIOD_DAYS:
        bad(422, f"A roster period cannot be longer than {MAX_PERIOD_DAYS} days")
    overlap = (db.query(DutyRoster)
               .filter(DutyRoster.cost_center_id == cost_center_id,
                       DutyRoster.period_from <= period_to, DutyRoster.period_to >= period_from)
               .first())
    if overlap is not None:
        bad(409, f"Period overlaps roster {overlap.roster_code} "
                 f"({overlap.period_from:%d-%b-%Y} to {overlap.period_to:%d-%b-%Y})")
    roster = DutyRoster(cost_center_id=cost_center_id, roster_code=code, roster_name=name,
                        period_from=period_from, period_to=period_to, created_by=user.id)
    db.add(roster)
    db.flush()
    db.add(DutyRosterVersion(roster_id=roster.roster_id, version_number=1,
                             status=RosterStatus.DRAFT, created_by=user.id))
    db.flush()
    return roster


def days_of(roster: DutyRoster) -> list[dt.date]:
    return [roster.period_from + dt.timedelta(days=i)
            for i in range((roster.period_to - roster.period_from).days + 1)]


# --------------------------------------------------------------------------
# The slots a date needs, read from the schedule version in force that day
# --------------------------------------------------------------------------
class Slot:
    """One crew duty to be filled: a schedule, a shift (or the whole day) and a role."""

    def __init__(self, schedule: BusSchedule, version, shift: ScheduleShift | None, crew_role: str):
        self.schedule = schedule
        self.version = version
        self.shift = shift
        self.crew_role = crew_role

    @property
    def key(self) -> tuple[int, int | None, str]:
        """Row identity in the grid. Keyed on the shift NUMBER, not its id, because the
        shift rows belong to a schedule version and a revision replaces them."""
        return (self.schedule.schedule_id, self.shift.shift_number if self.shift else None, self.crew_role)

    @property
    def span(self) -> tuple[int, int] | None:
        """Duty minutes from the schedule's day start, used to spot double booking."""
        return shift_span(self.shift) if self.shift else cycle_span(self.version)

    @property
    def label(self) -> str:
        role = self.crew_role.title()
        return f"{role} - {self.shift.shift_name}" if self.shift else role


def slots_for_date(schedules: list[BusSchedule], day: dt.date) -> list[Slot]:
    out = []
    for sch in schedules:
        v = version_for_date(sch, day)
        if v is None:                      # the bus does not run this schedule that day
            continue
        roles = [CrewRole.DRIVER] + ([CrewRole.CONDUCTOR] if v.conductor_required else [])
        for role in roles:
            if v.crew_mode == CrewMode.SHIFTS and v.shifts:
                for sh in sorted(v.shifts, key=lambda x: x.shift_number):
                    out.append(Slot(sch, v, sh, role))
            else:
                out.append(Slot(sch, v, None, role))
    return out


def schedules_of(db: Session, roster: DutyRoster) -> list[BusSchedule]:
    return (db.query(BusSchedule)
            .filter(BusSchedule.cost_center_id == roster.cost_center_id)
            .order_by(BusSchedule.schedule_code).all())


def resolve_slot(db: Session, roster: DutyRoster, day: dt.date, schedule_id: int,
                 shift_number: int | None, crew_role: str) -> Slot:
    """The slot a caller named, checked against what the date actually needs."""
    sch = db.get(BusSchedule, schedule_id)
    if sch is None or sch.cost_center_id != roster.cost_center_id:
        bad(422, f"Schedule {schedule_id} does not exist in this cost center")
    if not (roster.period_from <= day <= roster.period_to):
        bad(422, f"{day:%d-%b-%Y} is outside the roster period")
    for slot in slots_for_date([sch], day):
        if slot.key == (schedule_id, shift_number, crew_role):
            return slot
    v = version_for_date(sch, day)
    if v is None:
        bad(422, f"{sch.schedule_code} does not run on {day:%d-%b-%Y}")
    bad(422, f"{sch.schedule_code} on {day:%d-%b-%Y} has no "
             f"{crew_role.lower()} slot{f' for shift {shift_number}' if shift_number else ''}")


# --------------------------------------------------------------------------
# Reading and writing the draft grid
# --------------------------------------------------------------------------
def _by_slot(version: DutyRosterVersion) -> dict:
    """Assignments keyed the way the grid is: (schedule, shift number, role, date)."""
    out = {}
    for a in version.assignments:
        shift_number = a.shift.shift_number if a.shift else None
        out[(a.schedule_id, shift_number, a.crew_role, a.duty_date)] = a
    return out


def set_assignment(db: Session, roster: DutyRoster, version: DutyRosterVersion, day: dt.date,
                   schedule_id: int, shift_number: int | None, crew_role: str,
                   employee_id: int | None, remarks: str | None = None,
                   source: str = DutySource.MANUAL) -> DutyAssignment:
    """Put an employee in one slot of the draft (or clear it with employee_id=None)."""
    assert_draft(version)
    assert_open(roster, day)
    slot = resolve_slot(db, roster, day, schedule_id, shift_number, crew_role)
    if employee_id is not None:
        e = db.get(Employee, employee_id)
        if e is None or e.cost_center_id != roster.cost_center_id:
            bad(422, f"Employee {employee_id} does not exist in this cost center")

    shift_id = slot.shift.shift_id if slot.shift else None
    existing = next((a for a in version.assignments
                     if a.duty_date == day and a.schedule_id == schedule_id
                     and a.shift_id == shift_id and a.crew_role == crew_role), None)
    if existing is not None:
        existing.employee_id = employee_id
        existing.remarks = remarks
        existing.source = source
        return existing
    a = DutyAssignment(roster_version_id=version.roster_version_id, duty_date=day,
                       schedule_id=schedule_id, shift_id=shift_id, crew_role=crew_role,
                       employee_id=employee_id, remarks=remarks, source=source)
    db.add(a)
    version.assignments.append(a)
    return a


def copy_days(db: Session, roster: DutyRoster, version: DutyRosterVersion,
              source_from: dt.date, target_from: dt.date, day_count: int) -> dict:
    """Copy `day_count` days of the draft onto another stretch of dates - the grid's
    'copy previous week'. Slots the target date does not need are skipped, not forced."""
    assert_draft(version)
    existing = _by_slot(version)
    copied = skipped = 0
    schedules = schedules_of(db, roster)
    for i in range(day_count):
        src, dst = source_from + dt.timedelta(days=i), target_from + dt.timedelta(days=i)
        if not (roster.period_from <= dst <= roster.period_to) or (roster.locked_through and dst <= roster.locked_through):
            skipped += 1
            continue
        for slot in slots_for_date(schedules, dst):
            sch_id, shift_number, role = slot.key
            src_a = existing.get((sch_id, shift_number, role, src))
            if src_a is None or src_a.employee_id is None:
                continue
            set_assignment(db, roster, version, dst, sch_id, shift_number, role,
                           src_a.employee_id, source=DutySource.MANUAL)
            copied += 1
    return {"copied": copied, "skipped_days": skipped}


def add_extra(db: Session, roster: DutyRoster, version: DutyRosterVersion, day: dt.date,
              duty_type: str, crew_role: str, employee_id: int | None,
              start_time=None, end_time=None, remarks: str | None = None) -> DutyExtra:
    """Add a spare or shunting duty to one day. Several a day is normal, so each gets the
    next free slot number rather than replacing the last one."""
    assert_draft(version)
    assert_open(roster, day)
    if not (roster.period_from <= day <= roster.period_to):
        bad(422, f"{day:%d-%b-%Y} is outside the roster period")
    if employee_id is not None:
        e = db.get(Employee, employee_id)
        if e is None or e.cost_center_id != roster.cost_center_id:
            bad(422, f"Employee {employee_id} does not exist in this cost center")
    used = [x.slot_index for x in version.extras
            if x.duty_date == day and x.duty_type == duty_type and x.crew_role == crew_role]
    x = DutyExtra(roster_version_id=version.roster_version_id, duty_date=day, duty_type=duty_type,
                  crew_role=crew_role, slot_index=(max(used) + 1 if used else 1),
                  employee_id=employee_id, start_time=start_time, end_time=end_time, remarks=remarks)
    db.add(x)
    version.extras.append(x)
    return x


def update_extra(db: Session, roster: DutyRoster, version: DutyRosterVersion, x: DutyExtra,
                 employee_id: int | None, start_time=None, end_time=None,
                 remarks: str | None = None) -> DutyExtra:
    assert_draft(version)
    assert_open(roster, x.duty_date)
    if employee_id is not None:
        e = db.get(Employee, employee_id)
        if e is None or e.cost_center_id != roster.cost_center_id:
            bad(422, f"Employee {employee_id} does not exist in this cost center")
    x.employee_id, x.start_time, x.end_time, x.remarks = employee_id, start_time, end_time, remarks
    return x


def remove_extra(db: Session, roster: DutyRoster, version: DutyRosterVersion, x: DutyExtra) -> None:
    assert_draft(version)
    assert_open(roster, x.duty_date)
    db.delete(x)


def _extra_out(x: DutyExtra) -> dict:
    return {"extra_id": x.extra_id, "duty_date": x.duty_date.isoformat(), "duty_type": x.duty_type,
            "crew_role": x.crew_role, "slot_index": x.slot_index, "employee_id": x.employee_id,
            "employee_number": x.employee.employee_number if x.employee else None,
            "employee_name": x.employee.full_name if x.employee else None,
            "start_time": x.start_time.strftime("%H:%M") if x.start_time else None,
            "end_time": x.end_time.strftime("%H:%M") if x.end_time else None,
            "remarks": x.remarks}


def repeat_block(db: Session, roster: DutyRoster, version: DutyRosterVersion,
                 source_from: dt.date | None = None, day_count: int = 7) -> dict:
    """Fill the rest of the period by repeating one block of days - the first week by default.

    This is the roster's workhorse: a depot's crew cycle repeats weekly, so one typed week
    becomes a month. The last block is cut short when the period ends mid-week.
    """
    assert_draft(version)
    start = source_from or roster.period_from
    if not (roster.period_from <= start <= roster.period_to):
        bad(422, "The block to repeat must start inside the roster period")
    if day_count < 1:
        bad(422, "A block is at least one day")
    copied = blocks = 0
    target = start + dt.timedelta(days=day_count)
    while target <= roster.period_to:
        result = copy_days(db, roster, version, start, target, day_count)
        copied += result["copied"]
        blocks += 1
        target += dt.timedelta(days=day_count)
    return {"copied": copied, "blocks": blocks, "block_days": day_count,
            "repeated_from": start.isoformat()}


def _recorded(db: Session, roster: DutyRoster) -> dict:
    """What was recorded, keyed the way a grid cell is, with a duty's segments in order."""
    rows = (db.query(DutyActual)
            .filter(DutyActual.roster_id == roster.roster_id)
            .order_by(DutyActual.segment).all())
    out: dict[tuple, list[DutyActual]] = {}
    for x in rows:
        key = (x.duty_date, x.duty_type, x.schedule_id, x.shift_id, x.crew_role, x.slot_index)
        out.setdefault(key, []).append(x)
    return out


def _worked(segments: list[DutyActual]) -> dict:
    """One cell's actuals: who held the duty, in stretches, and how it ended up.

    A duty handed over part-way has a segment each, so the cell can show both names and when
    the change happened. The cell's overall status is the handover when there was one, because
    that is the thing worth seeing at a glance.
    """
    if not segments:
        return {"recorded": False, "actual_status": None, "actual": []}
    parts = []
    for s in segments:
        parts.append({
            "employee_id": s.actual_employee_id,
            "employee_number": s.actual_employee.employee_number if s.actual_employee else None,
            "employee_name": s.actual_employee.full_name if s.actual_employee else None,
            "status": s.status, "segment": s.segment,
            "from_time": s.duty_start_time.strftime("%H:%M") if s.duty_start_time else None,
            "to_time": s.duty_end_time.strftime("%H:%M") if s.duty_end_time else None,
            "reason": s.reason.reason_name if s.reason else None,
            "remarks": s.remarks or s.handover_reason,
        })
    status = segments[-1].status if len(segments) == 1 else "HANDED_OVER"
    return {"recorded": True, "actual_status": status, "actual": parts}


def grid(db: Session, roster: DutyRoster, version: DutyRosterVersion,
         with_actuals: bool = False) -> dict:
    """The matrix the roster screen draws: one row per duty slot, one column per date.

    With `with_actuals`, each cell also carries what was recorded on the day, so the same grid
    shows the plan against what happened.
    """
    schedules = schedules_of(db, roster)
    recorded = _recorded(db, roster) if with_actuals else {}
    assignments = _by_slot(version)
    days = days_of(roster)

    rows: dict[tuple, dict] = {}
    needed: dict[dt.date, set] = {}
    for day in days:
        slots = slots_for_date(schedules, day)
        needed[day] = {s.key for s in slots}
        for slot in slots:
            row = rows.get(slot.key)
            if row is None:
                span = slot.span
                row = rows[slot.key] = {
                    "schedule_id": slot.schedule.schedule_id,
                    "schedule_code": slot.schedule.schedule_code,
                    "fleet_number": slot.schedule.vehicle.fleet_number,
                    "shift_number": slot.shift.shift_number if slot.shift else None,
                    "shift_name": slot.shift.shift_name if slot.shift else None,
                    "crew_role": slot.crew_role,
                    "slot_label": slot.label,
                    # a shift has its own times; a one-crew day spans the schedule's whole cycle
                    "duty_from": slot.shift.start_time.strftime("%H:%M") if slot.shift
                                 else _hhmm(span[0] if span else None),
                    "duty_to": slot.shift.end_time.strftime("%H:%M") if slot.shift
                               else _hhmm(span[1] if span else None),
                    "duty_minutes": (span[1] - span[0]) if span else None,
                    "cells": {},
                }
            a = assignments.get((*slot.key, day))
            shift_id = slot.shift.shift_id if slot.shift else None
            cell = {
                "duty_date": day.isoformat(),
                "shift_id": shift_id,
                "employee_id": a.employee_id if a else None,
                "employee_number": a.employee.employee_number if a and a.employee else None,
                "employee_name": a.employee.full_name if a and a.employee else None,
                "source": a.source if a else None,
                "remarks": a.remarks if a else None,
                "locked": bool(roster.locked_through and day <= roster.locked_through),
            }
            if with_actuals:
                cell |= _worked(recorded.get((day, "SCHEDULE", slot.schedule.schedule_id,
                                              shift_id, slot.crew_role, 0), []))
            row["cells"][day.isoformat()] = cell

    ordered = sorted(rows.values(), key=lambda r: (r["schedule_code"], r["crew_role"] != CrewRole.DRIVER,
                                                   r["shift_number"] or 0))
    return {
        "roster_id": roster.roster_id, "roster_code": roster.roster_code, "roster_name": roster.roster_name,
        "period_from": roster.period_from, "period_to": roster.period_to,
        "locked_through": roster.locked_through,
        "roster_version_id": version.roster_version_id, "version_number": version.version_number,
        "status": version.status,
        "days": [{"duty_date": d.isoformat(), "weekday": d.strftime("%a"),
                  "locked": bool(roster.locked_through and d <= roster.locked_through),
                  "slots": len(needed[d])} for d in days],
        "rows": ordered,
        # a row shows for the whole period, but a slot the date does not need is not a gap
        "not_needed": {d.isoformat(): [list(k) for k in (set(rows) - needed[d])] for d in days},
        # spares and shunting: no bus, any number per day, so they hang off the date
        "extras": _extras_by_date(version, days, recorded if with_actuals else None),
        "with_actuals": with_actuals,
        "recorded_days": sorted({d.isoformat() for (d, *_rest) in recorded}) if with_actuals else [],
    }


def _extras_by_date(version: DutyRosterVersion, days: list[dt.date],
                    recorded: dict | None = None) -> dict:
    out = {d.isoformat(): {t: [] for t in DutyType.ALL} for d in days}
    for x in sorted(version.extras, key=lambda x: (x.duty_date, x.duty_type, x.slot_index)):
        day = out.get(x.duty_date.isoformat())
        if day is None:
            continue
        item = _extra_out(x)
        if recorded is not None:
            item |= _worked(recorded.get((x.duty_date, x.duty_type, None, None, x.crew_role,
                                          x.slot_index), []))
        day[x.duty_type].append(item)
    return out


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
class Issues:
    def __init__(self):
        self.items = []

    def add(self, severity, code, message, day=None, schedule_code=None, slot=None):
        self.items.append({"severity": severity, "code": code, "message": message,
                           "duty_date": day.isoformat() if day else None,
                           "schedule_code": schedule_code, "slot": slot})

    def error(self, code, message, **kw):
        self.add("ERROR", code, message, **kw)

    def warn(self, code, message, **kw):
        self.add("WARNING", code, message, **kw)

    def result(self) -> dict:
        errors = sum(1 for i in self.items if i["severity"] == "ERROR")
        return {"errors": errors, "warnings": len(self.items) - errors,
                "can_publish": errors == 0, "issues": self.items}


def validate(db: Session, roster: DutyRoster, version: DutyRosterVersion) -> dict:
    """Everything that must hold before a roster version can be published.

    The crew rules are the trip sheet's rules (`trip_sheet_service._validate_crew`) applied
    forward in time instead of backward: stint dates, staff type, and nobody in two places
    at once. The availability register only warns - the depot may call somebody in.
    """
    iss = Issues()
    schedules = schedules_of(db, roster)
    assignments = _by_slot(version)
    register = availability_service.register_for_range(db, [roster.cost_center_id],
                                                       roster.period_from, roster.period_to)

    for day in days_of(roster):
        locked = bool(roster.locked_through and day <= roster.locked_through)
        # per employee for this date: the spans they are rostered for, to catch overlaps
        booked: dict[int, list[tuple[tuple[int, int], Slot]]] = {}

        for slot in slots_for_date(schedules, day):
            a = assignments.get((*slot.key, day))
            where = {"day": day, "schedule_code": slot.schedule.schedule_code, "slot": slot.label}
            if a is None or a.employee_id is None:
                if not locked:
                    iss.error("UNFILLED", f"{slot.schedule.schedule_code} {slot.label} on "
                                          f"{day:%d-%b-%Y}: nobody rostered", **where)
                continue

            e = a.employee
            if e.staff_type != slot.crew_role:
                iss.error("CREW_TYPE", f"{e.full_name} is a {e.staff_type.lower().replace('_', ' ')}, "
                                       f"not a {slot.crew_role.lower()}", **where)
            if not availability_service.employed_on(e, day):
                iss.error("CREW_DATES", f"{e.full_name} is not on the rolls on {day:%d-%b-%Y} "
                                        f"(stint from {e.start_date:%d-%b-%Y}"
                                        f"{f' to {e.end_date:%d-%b-%Y}' if e.end_date else ''})", **where)
            elif e.end_date and e.end_date <= roster.period_to:
                iss.warn("CREW_STINT_ENDS", f"{e.full_name} leaves on {e.end_date:%d-%b-%Y}, "
                                            "inside this roster period", **where)
            if e.status != "ACTIVE":
                iss.error("CREW_INACTIVE", f"{e.full_name} is {e.status.lower()}", **where)
            for entry in register.get(e.employee_id, []):
                if entry.from_date <= day <= entry.to_date:
                    iss.warn("CREW_UNAVAILABLE",
                             f"{e.full_name} is marked {entry.status.replace('_', ' ').lower()} "
                             f"on {day:%d-%b-%Y}", **where)
                    break

            span = slot.span
            if span is not None:
                for other_span, other in booked.get(e.employee_id, []):
                    if span[0] < other_span[1] and other_span[0] < span[1]:
                        iss.error("CREW_DOUBLE_BOOKED",
                                  f"{e.full_name} is rostered on {other.schedule.schedule_code} "
                                  f"{other.label} at the same time on {day:%d-%b-%Y}", **where)
                booked.setdefault(e.employee_id, []).append((span, slot))

    # spares and shunting: an empty row is a leftover, and a person cannot be both
    # standby and driving a bus on the same day
    bus_days: dict[tuple[int, dt.date], str] = {}
    for day_key, a in assignments.items():
        if a.employee_id is not None:
            sch = db.get(BusSchedule, day_key[0])
            bus_days[(a.employee_id, a.duty_date)] = sch.schedule_code if sch else "a bus"
    for x in sorted(version.extras, key=lambda x: (x.duty_date, x.duty_type, x.slot_index)):
        what = f"{x.duty_type.title()} {x.slot_index}"
        where = {"day": x.duty_date, "slot": what}
        if x.employee_id is None:
            iss.warn("EXTRA_EMPTY", f"{what} on {x.duty_date:%d-%b-%Y} has nobody in it: "
                                    "fill it or remove the row", **where)
            continue
        e = x.employee
        if e.staff_type != x.crew_role:
            iss.error("CREW_TYPE", f"{e.full_name} is a {e.staff_type.lower().replace('_', ' ')}, "
                                   f"not a {x.crew_role.lower()}", **where)
        if not availability_service.employed_on(e, x.duty_date):
            iss.error("CREW_DATES", f"{e.full_name} is not on the rolls on "
                                    f"{x.duty_date:%d-%b-%Y}", **where)
        on_a_bus = bus_days.get((e.employee_id, x.duty_date))
        if on_a_bus:
            iss.warn("EXTRA_ALSO_ON_A_BUS", f"{e.full_name} is down as {what.lower()} on "
                                            f"{x.duty_date:%d-%b-%Y} and also drives {on_a_bus}",
                     **where)
        for entry in register.get(e.employee_id, []):
            if entry.from_date <= x.duty_date <= entry.to_date:
                iss.warn("CREW_UNAVAILABLE",
                         f"{e.full_name} is marked {entry.status.replace('_', ' ').lower()} "
                         f"on {x.duty_date:%d-%b-%Y}", **where)
                break

    # assignments left behind by a schedule revision: the slot no longer exists on that date
    for (sch_id, shift_number, role, day), a in assignments.items():
        if a.employee_id is None:
            continue
        sch = db.get(BusSchedule, sch_id)
        if not any(s.key == (sch_id, shift_number, role) for s in slots_for_date([sch], day)):
            iss.warn("SLOT_GONE", f"{sch.schedule_code} no longer needs a {role.lower()} on "
                                  f"{day:%d-%b-%Y}: {a.employee.full_name} is rostered for a slot "
                                  "that the schedule has since dropped",
                     day=day, schedule_code=sch.schedule_code)

    return iss.result()
