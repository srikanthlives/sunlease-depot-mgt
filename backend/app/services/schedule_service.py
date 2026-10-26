"""Schedule engine: building drafts, validation, bus-conflict detection, publishing."""
import datetime as dt
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.enums import ActivityType, Payability, ScheduleStatus, VersionStatus
from app.models.models import (
    ScheduleShift, TripSheet, BusSchedule, Location, Route, RouteDirection, RouteStop, ScheduledActivity, ScheduledCharging,
    ScheduledHalt, ScheduledLayover, ScheduledMovement, ScheduledStopTime, ScheduledTrip, ScheduleVersion, Vehicle,
)
from app.schemas.schemas import ActivityIn
from app.services import settings_service
from app.services.timeutil import fmt_minutes, rel_minutes, to_datetime

DAY = 1440


def bad(status: int, msg: str):
    raise HTTPException(status, msg)


def assert_draft(version: ScheduleVersion):
    if version.status != VersionStatus.DRAFT:
        bad(409, "Only a draft version can be changed. Create a new version to revise a published schedule.")


# --------------------------------------------------------------------------
# Writing activities (draft only)
# --------------------------------------------------------------------------
def _next_sequence(version: ScheduleVersion) -> int:
    return max((a.sequence_number for a in version.activities), default=0) + 1


def _check_location(db: Session, version: ScheduleVersion, loc_id: int, what: str = "Location"):
    """Locations belong to a company; a schedule may only use its own company's locations."""
    loc = db.get(Location, loc_id)
    company = version.schedule.cost_center.company_id if version.schedule.cost_center else None
    if loc is None or (company is not None and loc.company_id != company):
        bad(422, f"{what} {loc_id} does not exist in this company")
    return loc


def _apply_activity(db: Session, version: ScheduleVersion, act: ScheduledActivity, data: ActivityIn):
    for loc_id in (data.origin_location_id, data.destination_location_id):
        _check_location(db, version, loc_id)
    for detail, attr in ((data.charging, "charging_location_id"), (data.layover, "location_id"), (data.halt, "location_id")):
        if detail is not None:
            _check_location(db, version, getattr(detail, attr))
    act.activity_type = data.activity_type
    act.origin_location_id = data.origin_location_id
    act.destination_location_id = data.destination_location_id
    act.start_day_offset = data.start_day_offset
    act.scheduled_start_time = data.scheduled_start_time
    act.end_day_offset = data.end_day_offset
    act.scheduled_end_time = data.scheduled_end_time
    act.remarks = data.remarks
    # drop old detail rows, then create the one matching the type
    act.trip = act.movement = act.charging = act.layover = act.halt = None
    act.stop_times = []
    db.flush()
    if data.trip:
        t = data.trip
        route = db.get(Route, t.route_id)
        direction = db.get(RouteDirection, t.direction_id)
        if route is None or direction is None or route.cost_center_id != version.schedule.cost_center_id:
            bad(422, "Route or direction does not exist in this cost center")
        if direction.route_id != route.route_id:
            bad(422, "Selected direction does not belong to the selected route")
        dup = db.query(ScheduledTrip).filter(
            ScheduledTrip.schedule_version_id == version.schedule_version_id,
            ScheduledTrip.trip_number == t.trip_number,
            ScheduledTrip.activity_id != (act.activity_id or -1)).first()
        if dup:
            bad(409, f"Trip number {t.trip_number} is already used in this version")
        act.trip = ScheduledTrip(
            schedule_version_id=version.schedule_version_id, trip_number=t.trip_number,
            route_id=t.route_id, direction_id=t.direction_id, planned_distance_km=t.planned_distance_km,
            planned_start_soc_pct=t.planned_start_soc_pct, planned_end_soc_pct=t.planned_end_soc_pct)
        valid_stop_ids = {s.route_stop_id for s in direction.stops}
        seen = set()
        for s in t.stops:
            if s.route_stop_id not in valid_stop_ids:
                bad(422, f"Stop {s.route_stop_id} does not belong to the selected direction")
            if s.stop_sequence in seen:
                bad(422, f"Duplicate stop sequence {s.stop_sequence} in trip")
            seen.add(s.stop_sequence)
            act.stop_times.append(ScheduledStopTime(**s.model_dump()))
    if data.movement:
        act.movement = ScheduledMovement(**data.movement.model_dump())
    if data.charging:
        if db.get(Location, data.charging.charging_location_id) is None:
            bad(422, "Charging location does not exist")
        act.charging = ScheduledCharging(**data.charging.model_dump())
    if data.layover:
        if db.get(Location, data.layover.location_id) is None:
            bad(422, "Layover location does not exist")
        act.layover = ScheduledLayover(**data.layover.model_dump())
    if data.halt:
        if db.get(Location, data.halt.location_id) is None:
            bad(422, "Halt location does not exist")
        act.halt = ScheduledHalt(**data.halt.model_dump())


def add_activity(db: Session, version: ScheduleVersion, data: ActivityIn) -> ScheduledActivity:
    assert_draft(version)
    seq = data.sequence_number or _next_sequence(version)
    if any(a.sequence_number == seq for a in version.activities):
        bad(409, f"Sequence number {seq} is already used in this version")
    act = ScheduledActivity(schedule_version_id=version.schedule_version_id, sequence_number=seq,
                            activity_type=data.activity_type, origin_location_id=data.origin_location_id,
                            destination_location_id=data.destination_location_id,
                            scheduled_start_time=data.scheduled_start_time, scheduled_end_time=data.scheduled_end_time)
    db.add(act)
    db.flush()
    _apply_activity(db, version, act, data)
    db.flush()
    db.refresh(version)
    return act


def update_activity(db: Session, act: ScheduledActivity, data: ActivityIn) -> ScheduledActivity:
    version = act.version
    assert_draft(version)
    if data.sequence_number and data.sequence_number != act.sequence_number:
        if any(a.sequence_number == data.sequence_number for a in version.activities):
            bad(409, f"Sequence number {data.sequence_number} is already used in this version")
        act.sequence_number = data.sequence_number
    _apply_activity(db, version, act, data)
    db.flush()
    return act


def delete_activity(db: Session, act: ScheduledActivity):
    assert_draft(act.version)
    db.delete(act)
    db.flush()


def reorder(db: Session, version: ScheduleVersion, ids: list[int]):
    assert_draft(version)
    current = {a.activity_id: a for a in version.activities}
    if sorted(ids) != sorted(current):
        bad(422, "activity_ids must list every activity of the version exactly once")
    # two-phase renumber to dodge the unique (version, sequence) constraint
    for a in current.values():
        a.sequence_number = a.sequence_number + 100000
    db.flush()
    for i, aid in enumerate(ids, start=1):
        current[aid].sequence_number = i
    db.flush()


def _detail(a: ScheduledActivity):
    return a.trip or a.movement or a.charging or a.layover or a.halt


def _soc(a: ScheduledActivity, end: bool):
    d = _detail(a)
    return getattr(d, "planned_end_soc_pct" if end else "planned_start_soc_pct", None) if d else None


def _at(minutes: int) -> tuple[int, dt.time]:
    return minutes // DAY, dt.time((minutes % DAY) // 60, minutes % 60)


def fill_layovers(db: Session, version: ScheduleVersion) -> dict:
    """Carry SOC through the stationary activities and tidy layovers:
    - layovers, charging and halts take their start SOC from the previous activity's end SOC and their end SOC
      from the next activity's start SOC (when those are entered);
    - layovers also snap their times to the neighbours (start when the previous ends, end when the next starts);
      charging and halts keep their planned times;
    - idle gaps at one location become new layovers. Gaps next to a Halt are left alone (they belong to the
      halt), and gaps where the bus would have to move are only reported."""
    assert_draft(version)
    acts = sorted(version.activities, key=lambda a: a.sequence_number)
    updated, charging_updated, halt_updated, created, skipped = 0, 0, 0, [], []
    for i, a in enumerate(acts):
        d = {ActivityType.LAYOVER: a.layover, ActivityType.CHARGING: a.charging, ActivityType.HALT: a.halt}.get(a.activity_type)
        if d is None:
            continue
        prev, nxt = (acts[i - 1] if i else None), (acts[i + 1] if i + 1 < len(acts) else None)
        s0, e0 = activity_span(a)
        before = (s0, e0, d.planned_start_soc_pct, d.planned_end_soc_pct)
        if prev and _soc(prev, True) is not None:
            d.planned_start_soc_pct = _soc(prev, True)
        if nxt and _soc(nxt, False) is not None:
            d.planned_end_soc_pct = _soc(nxt, False)
        s1, e1 = s0, e0
        if a.activity_type == ActivityType.LAYOVER:
            s1 = activity_span(prev)[1] if prev else s0
            e1 = activity_span(nxt)[0] if nxt else e0
            if e1 <= s1:
                skipped.append(f"#{a.sequence_number} layover: neighbours overlap, times left as they are (SOC filled)")
                s1, e1 = s0, e0
            else:
                a.start_day_offset, a.scheduled_start_time = _at(s1)
                a.end_day_offset, a.scheduled_end_time = _at(e1)
        if (s1, e1, d.planned_start_soc_pct, d.planned_end_soc_pct) != before:
            if a.activity_type == ActivityType.LAYOVER:
                updated += 1
            elif a.activity_type == ActivityType.CHARGING:
                charging_updated += 1
            else:
                halt_updated += 1
    # idle gaps between two activities at the same place become layovers
    order = []
    for i, a in enumerate(acts):
        order.append(a)
        nxt = acts[i + 1] if i + 1 < len(acts) else None
        if nxt is None:
            continue
        gap_s, gap_e = activity_span(a)[1], activity_span(nxt)[0]
        if gap_e <= gap_s or ActivityType.HALT in (a.activity_type, nxt.activity_type):
            continue
        if a.destination_location_id != nxt.origin_location_id:
            skipped.append(f"Gap of {fmt_minutes(gap_e - gap_s)} between #{a.sequence_number} and #{nxt.sequence_number} "
                           f"changes location ({a.destination.location_name} -> {nxt.origin.location_name}) - add a movement")
            continue
        loc = a.destination
        (so, st), (eo, et) = _at(gap_s), _at(gap_e)
        lay = ScheduledActivity(schedule_version_id=version.schedule_version_id, sequence_number=500000 + len(order),  # out of reorder()'s +100000 range
                                activity_type=ActivityType.LAYOVER, origin_location_id=loc.location_id,
                                destination_location_id=loc.location_id, start_day_offset=so, scheduled_start_time=st,
                                end_day_offset=eo, scheduled_end_time=et)
        lay.layover = ScheduledLayover(location_id=loc.location_id,
                                       layover_purpose="TERMINAL_RECOVERY" if loc.location_type == "TERMINAL" else "INTER_TRIP",
                                       planned_start_soc_pct=_soc(a, True), planned_end_soc_pct=_soc(nxt, False))
        version.activities.append(lay)
        order.append(lay)
        created.append(lay)
    if created:
        db.flush()
        reorder(db, version, [x.activity_id for x in order])
    db.flush()
    return {"updated": updated, "charging_updated": charging_updated, "halt_updated": halt_updated,
            "created": len(created), "skipped": skipped}


def copy_version_content(db: Session, src: ScheduleVersion, dst: ScheduleVersion):
    dst.crew_mode, dst.conductor_required = src.crew_mode, src.conductor_required
    for sh in src.shifts:
        db.add(ScheduleShift(schedule_version_id=dst.schedule_version_id, shift_number=sh.shift_number,
                             shift_name=sh.shift_name, start_day_offset=sh.start_day_offset, start_time=sh.start_time,
                             end_day_offset=sh.end_day_offset, end_time=sh.end_time,
                             change_location_id=sh.change_location_id))
    for a in src.activities:
        new = ScheduledActivity(
            schedule_version_id=dst.schedule_version_id, sequence_number=a.sequence_number,
            activity_type=a.activity_type, origin_location_id=a.origin_location_id,
            destination_location_id=a.destination_location_id, start_day_offset=a.start_day_offset,
            scheduled_start_time=a.scheduled_start_time, end_day_offset=a.end_day_offset,
            scheduled_end_time=a.scheduled_end_time, remarks=a.remarks)
        db.add(new)
        db.flush()
        if a.trip:
            t = a.trip
            new.trip = ScheduledTrip(
                schedule_version_id=dst.schedule_version_id, trip_number=t.trip_number, route_id=t.route_id,
                direction_id=t.direction_id, planned_distance_km=t.planned_distance_km,
                planned_start_soc_pct=t.planned_start_soc_pct, planned_end_soc_pct=t.planned_end_soc_pct)
            for s in a.stop_times:
                new.stop_times.append(ScheduledStopTime(
                    route_stop_id=s.route_stop_id, stop_sequence=s.stop_sequence,
                    arrival_day_offset=s.arrival_day_offset, scheduled_arrival_time=s.scheduled_arrival_time,
                    departure_day_offset=s.departure_day_offset, scheduled_departure_time=s.scheduled_departure_time,
                    planned_soc_pct=s.planned_soc_pct))
        if a.movement:
            m = a.movement
            new.movement = ScheduledMovement(
                movement_purpose=m.movement_purpose, planned_distance_km=m.planned_distance_km,
                planned_start_soc_pct=m.planned_start_soc_pct, planned_end_soc_pct=m.planned_end_soc_pct,
                payability_status=m.payability_status, payment_basis=m.payment_basis)
        if a.charging:
            c = a.charging
            new.charging = ScheduledCharging(
                charging_location_id=c.charging_location_id, planned_start_soc_pct=c.planned_start_soc_pct,
                planned_end_soc_pct=c.planned_end_soc_pct, expected_energy_kwh=c.expected_energy_kwh)
        if a.layover:
            l = a.layover
            new.layover = ScheduledLayover(location_id=l.location_id, layover_purpose=l.layover_purpose,
                                           planned_start_soc_pct=l.planned_start_soc_pct,
                                           planned_end_soc_pct=l.planned_end_soc_pct)
        if a.halt:
            hl = a.halt
            new.halt = ScheduledHalt(location_id=hl.location_id, planned_start_soc_pct=hl.planned_start_soc_pct,
                                     planned_end_soc_pct=hl.planned_end_soc_pct)
    db.flush()


# --------------------------------------------------------------------------
# Derived values
# --------------------------------------------------------------------------
def activity_span(a: ScheduledActivity) -> tuple[int, int]:
    return rel_minutes(a.start_day_offset, a.scheduled_start_time), rel_minutes(a.end_day_offset, a.scheduled_end_time)


def cycle_span(version: ScheduleVersion) -> tuple[int, int] | None:
    spans = [activity_span(a) for a in version.activities]
    if not spans:
        return None
    return min(s for s, _ in spans), max(e for _, e in spans)


def activity_km(a: ScheduledActivity) -> Decimal:
    if a.trip:
        return a.trip.planned_distance_km or Decimal(0)
    if a.movement:
        return a.movement.planned_distance_km or Decimal(0)
    return Decimal(0)


def _halt_inside(version: ScheduleVersion, op: tuple[int, int]) -> int:
    """Minutes of Halt blocks that fall between the first and last in-service activity (e.g. a mid-day depot halt)."""
    total = 0
    for a in version.activities:
        if a.activity_type == ActivityType.HALT:
            s, e = activity_span(a)
            total += max(0, min(e, op[1]) - max(s, op[0]))
    return total


def summarize(version: ScheduleVersion) -> dict:
    revenue = sum((a.trip.planned_distance_km for a in version.activities if a.trip), Decimal(0))
    non_rev = sum((a.movement.planned_distance_km for a in version.activities if a.movement), Decimal(0))
    # revenue/non-revenue is about passengers; payability is set per movement, independently
    non_rev_pay = {p: 0.0 for p in Payability.ALL}
    for a in version.activities:
        if a.movement:
            non_rev_pay[a.movement.payability_status] += float(a.movement.planned_distance_km)
    mins = {t: 0 for t in ActivityType.ALL}
    for a in version.activities:
        s, e = activity_span(a)
        mins[a.activity_type] += max(0, e - s)
    span = cycle_span(version)
    # Cycle time leaves out Halt blocks (depot / night-halt time); bus conflicts still use the full span.
    in_service = [activity_span(a) for a in version.activities if a.activity_type != ActivityType.HALT]
    op = (min(s for s, _ in in_service), max(e for _, e in in_service)) if in_service else None
    return {
        "activity_count": len(version.activities),
        "trip_count": sum(1 for a in version.activities if a.trip),
        "revenue_km": float(revenue), "non_revenue_km": float(non_rev),
        "non_revenue_km_by_payability": non_rev_pay,
        # billed: every passenger-trip km plus movement km marked payable
        "billable_km": float(revenue) + non_rev_pay[Payability.PAYABLE], "total_km": float(revenue + non_rev),
        "minutes_by_type": mins,
        "steering_minutes": mins[ActivityType.PASSENGER_TRIP] + mins[ActivityType.NON_REVENUE_MOVEMENT],
        "operating_start_min": op[0] if op else None, "operating_end_min": op[1] if op else None,
        "operating_minutes": max(0, (op[1] - op[0]) - _halt_inside(version, op)) if op else 0,
        "operating_spans_days": ((op[1] - 1) // DAY + 1) if op else 0,
        "halt_minutes": mins[ActivityType.HALT],
        "cycle_start_min": span[0] if span else None, "cycle_end_min": span[1] if span else None,
        "cycle_minutes": (span[1] - span[0]) if span else 0,
        "spans_days": ((span[1] - 1) // DAY + 1) if span else 0,
    }


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
class Issues:
    def __init__(self):
        self.items: list[dict] = []

    def add(self, severity, code, message, activity_id=None, sequence=None):
        self.items.append({"severity": severity, "code": code, "message": message,
                           "activity_id": activity_id, "sequence_number": sequence})

    def error(self, code, message, a=None):
        self.add("ERROR", code, message, a.activity_id if a else None, a.sequence_number if a else None)

    def warn(self, code, message, a=None):
        self.add("WARNING", code, message, a.activity_id if a else None, a.sequence_number if a else None)


def _stop_event_minutes(s: ScheduledStopTime):
    """(arrival, departure) relative minutes or None."""
    arr = rel_minutes(s.arrival_day_offset or 0, s.scheduled_arrival_time) if s.scheduled_arrival_time else None
    dep = rel_minutes(s.departure_day_offset or 0, s.scheduled_departure_time) if s.scheduled_departure_time else None
    return arr, dep


def validate_version(db: Session, version: ScheduleVersion) -> dict:
    iss = Issues()
    schedule = version.schedule
    vehicle = schedule.vehicle
    cfg = settings_service.get_all(db, schedule.cost_center_id)
    req_soc = cfg["require_stop_soc"] == "true"
    tol = float(cfg["distance_tolerance_pct"])
    gap_warn = float(cfg["gap_warn_minutes"])

    # --- header
    if vehicle is None or vehicle.status != "ACTIVE":
        iss.error("VEHICLE_INACTIVE", "The assigned vehicle is not active")
    if version.valid_to and version.valid_to < version.valid_from:
        iss.error("VERSION_DATES", "Version valid_to is before valid_from")
    if version.valid_from < schedule.effective_from or (
            schedule.effective_to and version.valid_from > schedule.effective_to):
        iss.warn("VERSION_OUTSIDE_EFFECTIVE", "Version valid_from is outside the schedule's effective dates")
    acts = sorted(version.activities, key=lambda a: a.sequence_number)
    if not acts:
        iss.error("NO_ACTIVITIES", "A schedule needs at least one activity")

    # --- per activity
    trip_numbers = {}
    for a in acts:
        s, e = activity_span(a)
        label = f"#{a.sequence_number}"
        if e <= s:
            iss.error("DURATION", f"{label}: end must be later than start (check the day offsets)", a)
        for loc in (a.origin, a.destination):
            if not loc.is_active:
                iss.error("LOCATION_INACTIVE", f"{label}: location {loc.location_name} is inactive", a)
        if a.activity_type == ActivityType.PASSENGER_TRIP:
            _validate_trip(db, a, iss, label, s, e, req_soc, tol, trip_numbers)
        elif a.activity_type == ActivityType.NON_REVENUE_MOVEMENT:
            m = a.movement
            if m is None:
                iss.error("MISSING_DETAIL", f"{label}: movement details missing", a)
            else:
                if a.origin_location_id == a.destination_location_id and m.planned_distance_km > 0:
                    iss.warn("MOVEMENT_SAME_LOCATION", f"{label}: movement has distance but same origin and destination", a)
                _check_soc(iss, a, label, m.planned_start_soc_pct, m.planned_end_soc_pct)
        elif a.activity_type == ActivityType.HALT:
            hl = a.halt
            if hl is None:
                iss.error("MISSING_DETAIL", f"{label}: halt details missing", a)
            else:
                if not (a.origin_location_id == a.destination_location_id == hl.location_id):
                    iss.error("HALT_LOCATION", f"{label}: a halt is stationary - origin, destination and location must match", a)
                # SOC may rise (charging inside the halt) or fall - only the range is checked
                _check_soc(iss, a, label, hl.planned_start_soc_pct, hl.planned_end_soc_pct)
        elif a.activity_type == ActivityType.CHARGING:
            c = a.charging
            if c is None:
                iss.error("MISSING_DETAIL", f"{label}: charging details missing", a)
            else:
                loc = c.charging_location
                if not loc.supports_charging:
                    iss.error("CHARGER_UNSUPPORTED", f"{label}: {loc.location_name} does not support charging", a)
                if not loc.is_active:
                    iss.error("LOCATION_INACTIVE", f"{label}: charging location {loc.location_name} is inactive", a)
                if not (a.origin_location_id == a.destination_location_id == c.charging_location_id):
                    iss.error("CHARGING_LOCATION", f"{label}: charging is stationary - origin, destination and charging location must match "
                                                   "(use a separate movement to reach the charger)", a)
                if c.planned_start_soc_pct is not None and c.planned_end_soc_pct is not None \
                        and c.planned_end_soc_pct < c.planned_start_soc_pct:
                    iss.warn("CHARGING_SOC_DROP", f"{label}: SOC decreases during charging", a)
        elif a.activity_type == ActivityType.LAYOVER:
            l = a.layover
            if l is None:
                iss.error("MISSING_DETAIL", f"{label}: layover details missing", a)
            else:
                if not (a.origin_location_id == a.destination_location_id == l.location_id):
                    iss.error("LAYOVER_LOCATION", f"{label}: layover origin, destination and location must match", a)
                _check_soc(iss, a, label, l.planned_start_soc_pct, l.planned_end_soc_pct)
                # SOC may fall (bus powered, A/C on) but cannot rise without charging
                if l.planned_start_soc_pct is not None and l.planned_end_soc_pct is not None \
                        and l.planned_end_soc_pct > l.planned_start_soc_pct:
                    iss.warn("LAYOVER_SOC_RISE", f"{label}: SOC rises during a layover - add a charging activity instead", a)

    # --- chronology between consecutive activities
    prev = None
    for a in acts:
        s, e = activity_span(a)
        if prev is not None:
            ps, pe = activity_span(prev)
            if s < pe:
                iss.error("OVERLAP", f"#{prev.sequence_number} and #{a.sequence_number} overlap by {fmt_minutes(pe - s)}", a)
            elif s - pe > gap_warn:
                iss.warn("GAP", f"Unexplained gap of {fmt_minutes(s - pe)} before #{a.sequence_number}", a)
            if prev.destination_location_id != a.origin_location_id:
                iss.warn("LOCATION_JUMP", f"#{a.sequence_number} starts at {a.origin.location_name} but the previous activity ended at "
                                          f"{prev.destination.location_name}", a)
        prev = a

    _validate_crew(version, iss)

    # --- bus conflicts
    iss_conflicts(db, version, iss)

    errors = [i for i in iss.items if i["severity"] == "ERROR"]
    warnings = [i for i in iss.items if i["severity"] == "WARNING"]
    return {"valid": not errors, "error_count": len(errors), "warning_count": len(warnings),
            "issues": iss.items, "summary": summarize(version)}


def _check_soc(iss, a, label, ss, es):
    for v in (ss, es):
        if v is not None and not (0 <= v <= 100):
            iss.error("SOC_RANGE", f"{label}: SOC must be between 0 and 100", a)


def _validate_trip(db, a, iss, label, s, e, req_soc, tol, trip_numbers):
    t = a.trip
    if t is None:
        iss.error("MISSING_DETAIL", f"{label}: passenger trip details missing", a)
        return
    if t.trip_number in trip_numbers:
        iss.error("TRIP_NUMBER_DUP", f"{label}: trip number {t.trip_number} duplicates #{trip_numbers[t.trip_number]}", a)
    trip_numbers[t.trip_number] = a.sequence_number
    route, direction = t.route, t.direction
    if direction.route_id != route.route_id:
        iss.error("DIRECTION_MISMATCH", f"{label}: direction {direction.direction_code} is not part of route {route.route_code}", a)
    if route.status != "ACTIVE" or not direction.is_active:
        iss.error("ROUTE_INACTIVE", f"{label}: route or direction is inactive", a)
    if a.origin_location_id != direction.start_terminal_id or a.destination_location_id != direction.end_terminal_id:
        iss.error("TERMINAL_MISMATCH", f"{label}: origin/destination must be the direction's terminals "
                                       f"({direction.start_terminal.location_name} -> {direction.end_terminal.location_name})", a)
    # distance reconciliation
    rd = float(direction.total_distance_km or 0)
    if rd > 0:
        diff = abs(float(t.planned_distance_km) - rd) / rd * 100
        if diff > tol:
            iss.error("DISTANCE_MISMATCH", f"{label}: trip distance {t.planned_distance_km} km differs from route distance "
                                           f"{direction.total_distance_km} km by {diff:.1f}% (tolerance {tol:g}%)", a)
    _check_soc(iss, a, label, t.planned_start_soc_pct, t.planned_end_soc_pct)

    stops = sorted(a.stop_times, key=lambda x: x.stop_sequence)
    if len(stops) < 2:
        iss.error("STOPS_MIN", f"{label}: a passenger trip needs at least two stops with times", a)
        return
    dir_stops = {rs.route_stop_id: rs for rs in direction.stops}
    last_rs_seq = 0
    for st in stops:
        rs = dir_stops.get(st.route_stop_id)
        if rs is None:
            iss.error("STOP_DIRECTION", f"{label}: stop {st.route_stop_id} is not in direction {direction.direction_code}", a)
            continue
        if rs.stop_sequence <= last_rs_seq:
            iss.error("STOP_ORDER", f"{label}: stops are not in the direction's sequence", a)
        last_rs_seq = rs.stop_sequence
    if dir_stops:
        first_rs = min(dir_stops.values(), key=lambda r: r.stop_sequence)
        last_rs = max(dir_stops.values(), key=lambda r: r.stop_sequence)
        if stops[0].route_stop_id != first_rs.route_stop_id:
            iss.error("STOP_FIRST", f"{label}: the first stop must be the direction's origin terminal", a)
        if stops[-1].route_stop_id != last_rs.route_stop_id:
            iss.error("STOP_LAST", f"{label}: the last stop must be the direction's destination terminal", a)

    n = len(stops)
    prev_t = None
    for i, st in enumerate(stops):
        arr, dep = _stop_event_minutes(st)
        loc = st.route_stop.location.location_name if st.route_stop else st.stop_sequence
        if i == 0:
            if dep is None:
                iss.error("STOP_TIME_MISSING", f"{label}: departure time missing at origin {loc}", a)
            elif dep != s:
                iss.error("STOP_START_MISMATCH", f"{label}: origin departure must equal the activity start time", a)
        elif i == n - 1:
            if arr is None:
                iss.error("STOP_TIME_MISSING", f"{label}: arrival time missing at destination {loc}", a)
            elif arr != e:
                iss.error("STOP_END_MISMATCH", f"{label}: destination arrival must equal the activity end time", a)
        else:
            if arr is None or dep is None:
                iss.error("STOP_TIME_MISSING", f"{label}: arrival and departure times are required at {loc}", a)
        if arr is not None and dep is not None and dep < arr:
            iss.error("STOP_DWELL", f"{label}: departure before arrival at {loc}", a)
        for tm in (arr, dep):
            if tm is not None:
                if prev_t is not None and tm < prev_t:
                    iss.error("STOP_CHRONO", f"{label}: stop times are not chronological at {loc}", a)
                prev_t = tm
        # readings
        if st.planned_soc_pct is not None and not (0 <= st.planned_soc_pct <= 100):
            iss.error("SOC_RANGE", f"{label}: SOC at {loc} must be between 0 and 100", a)
        if req_soc and st.planned_soc_pct is None:
            iss.error("SOC_REQUIRED", f"{label}: planned SOC required at {loc}", a)


# --------------------------------------------------------------------------
# Bus conflicts and version-date conflicts
# --------------------------------------------------------------------------
def _range(v: ScheduleVersion):
    return v.valid_from, v.valid_to or dt.date.max


def _occurrences_overlap(a_span, a_range, b_span, b_range) -> int | None:
    """Daily recurrence: occurrence of A on date d covers [d+sa, d+ea]; B on d+n covers
    [d+n*DAY+sb, d+n*DAY+eb]. Returns a shift n (days) at which both occur and overlap."""
    sa, ea = a_span
    sb, eb = b_span
    # overlap needs (sa - eb)/DAY < n < (ea - sb)/DAY
    lo = (sa - eb) // DAY - 1
    hi = (ea - sb) // DAY + 1
    for n in range(lo, hi + 1):
        if not (sa < eb + n * DAY and sb + n * DAY < ea):
            continue
        # need d in A range with d+n in B range
        d_lo = max(a_range[0], b_range[0] - dt.timedelta(days=n))
        d_hi = min(a_range[1], b_range[1] - dt.timedelta(days=n)) if b_range[1] != dt.date.max else a_range[1]
        if d_lo <= d_hi:
            return n
    return None


def iss_conflicts(db: Session, version: ScheduleVersion, iss: Issues):
    span = cycle_span(version)
    if span is None:
        return
    schedule = version.schedule
    vr = _range(version)
    # own cycle must not run into its own next occurrence
    if span[1] - span[0] > DAY:
        iss.error("SELF_OVERLAP", f"The operating cycle lasts {fmt_minutes(span[1] - span[0])} - longer than 24 hours, so "
                                  "it overlaps the next day's occurrence for the same bus")
    # same-schedule published versions must not overlap in dates
    for other in schedule.versions:
        if other.schedule_version_id == version.schedule_version_id or other.status == VersionStatus.DRAFT:
            continue
        orange = _range(other)
        if vr[0] <= orange[1] and orange[0] <= vr[1] and other.valid_from >= version.valid_from:
            iss.error("VERSION_DATE_CONFLICT", f"Version {other.version_number} (from {other.valid_from}) is already published "
                                               "on or after this version's start date")
    # other published schedules on the same physical bus
    others = (db.query(ScheduleVersion).join(BusSchedule)
              .filter(BusSchedule.vehicle_id == schedule.vehicle_id,
                      ScheduleVersion.schedule_id != schedule.schedule_id,
                      BusSchedule.status != ScheduleStatus.RETIRED,
                      ScheduleVersion.status == VersionStatus.PUBLISHED).all())
    for o in others:
        ospan = cycle_span(o)
        if ospan is None:
            continue
        n = _occurrences_overlap(span, vr, ospan, _range(o))
        if n is not None:
            when = "the same day" if n == 0 else f"{abs(n)} day(s) {'later' if n > 0 else 'earlier'}"
            iss.error("BUS_CONFLICT", f"Bus {schedule.vehicle.fleet_number} is already used by schedule "
                                      f"{o.schedule.schedule_code} v{o.version_number} ({when} overlap)")


# --------------------------------------------------------------------------
# Publishing
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Crew pattern (one driver for the day, or shifts) - used to lay out trip-sheet crew
# --------------------------------------------------------------------------
def set_crew(db: Session, version: ScheduleVersion, mode: str, conductor_required: bool, shifts) -> None:
    assert_draft(version)
    company = version.schedule.cost_center.company_id if version.schedule.cost_center else None
    version.crew_mode, version.conductor_required = mode, conductor_required
    version.shifts = []
    db.flush()
    for i, sh in enumerate(shifts if mode == "SHIFTS" else [], start=1):
        if sh.change_location_id is not None:
            loc = db.get(Location, sh.change_location_id)
            if loc is None or (company is not None and loc.company_id != company):
                bad(422, f"Shift change location {sh.change_location_id} does not exist in this company")
        version.shifts.append(ScheduleShift(shift_number=i, **sh.model_dump()))
    db.flush()


def shift_span(sh: ScheduleShift) -> tuple[int, int]:
    return rel_minutes(sh.start_day_offset, sh.start_time), rel_minutes(sh.end_day_offset, sh.end_time)


def _validate_crew(version: ScheduleVersion, iss: "Issues"):
    if version.crew_mode != "SHIFTS":
        return
    if not version.shifts:
        iss.error("SHIFTS_MISSING", "Crew is set to shifts but no shifts are defined")
        return
    spans = sorted((shift_span(sh), sh) for sh in version.shifts)
    for (s, e), sh in spans:
        if e <= s:
            iss.error("SHIFT_TIMES", f"Shift {sh.shift_name}: end must be after start (check the day offset)")
    for ((s1, e1), a), ((s2, e2), b) in zip(spans, spans[1:]):
        if s2 < e1:
            iss.error("SHIFT_OVERLAP", f"Shifts {a.shift_name} and {b.shift_name} overlap")
        elif s2 > e1:
            iss.warn("SHIFT_GAP", f"No shift covers {fmt_minutes(s2 - e1)} between {a.shift_name} and {b.shift_name}")
    driving = [activity_span(a) for a in version.activities
               if a.activity_type in (ActivityType.PASSENGER_TRIP, ActivityType.NON_REVENUE_MOVEMENT)]
    if driving:
        first, last = min(s for s, _ in driving), max(e for _, e in driving)
        if spans[0][0][0] > first or max(e for (_, e), _ in spans) < last:
            iss.warn("SHIFT_COVERAGE", "Shifts do not cover all driving from the first to the last trip or movement")


def first_trip_sheet_date(db: Session, schedule_id: int) -> dt.date | None:
    row = (db.query(TripSheet.operating_date).filter(TripSheet.schedule_id == schedule_id)
           .order_by(TripSheet.operating_date).first())
    return row[0] if row else None


def change_effective_from(db: Session, schedule: BusSchedule, new: dt.date) -> None:
    """Move the schedule's start date. Draft versions that started with the schedule move with it;
    published history and trip sheets are never left outside the schedule's dates."""
    old = schedule.effective_from
    if new == old:
        return
    if schedule.effective_to and new > schedule.effective_to:
        bad(422, "Effective from cannot be after effective to")
    first = first_trip_sheet_date(db, schedule.schedule_id)
    if first and new > first:
        bad(409, f"A trip sheet exists on {first.isoformat()} - effective from cannot be later than that")
    early = [v for v in schedule.versions if v.status != VersionStatus.DRAFT and v.valid_from < new]
    if early:
        v = min(early, key=lambda x: x.valid_from)
        bad(409, f"Published v{v.version_number} starts on {v.valid_from.isoformat()} - effective from cannot be later "
                 "(unpublish it first, or publish a new version from the new date)")
    for v in schedule.versions:
        if v.status == VersionStatus.DRAFT and (v.valid_from == old or v.valid_from < new):
            v.valid_from = new
            if v.valid_to and v.valid_to < new:
                v.valid_to = None
    schedule.effective_from = new


def last_trip_sheet_date(db: Session, schedule_id: int) -> dt.date | None:
    row = (db.query(TripSheet.operating_date).filter(TripSheet.schedule_id == schedule_id)
           .order_by(TripSheet.operating_date.desc()).first())
    return row[0] if row else None


def publish(db: Session, version: ScheduleVersion, user, change_reason: str | None, ack: bool) -> dict:
    assert_draft(version)
    last = last_trip_sheet_date(db, version.schedule_id)
    if last and version.valid_from <= last:
        # publishing would change which version applies on dates that already have trip sheets
        bad(409, f"Trip sheets exist up to {last.isoformat()} - a new version must start after that date")
    result = validate_version(db, version)
    if not result["valid"]:
        bad(422, {"message": "Version has validation errors", "issues": result["issues"]})
    if result["warning_count"] and not ack:
        bad(422, {"message": "Version has warnings that must be acknowledged", "issues": result["issues"],
                  "needs_acknowledgement": True})
    schedule = version.schedule
    # close earlier published versions of the same schedule that run into this one
    for other in schedule.versions:
        if other.schedule_version_id == version.schedule_version_id or other.status == VersionStatus.DRAFT:
            continue
        before = (other.status, other.valid_to)
        if other.valid_to is None or other.valid_to >= version.valid_from:
            if other.valid_from >= version.valid_from:
                bad(409, "An existing published version starts on or after this version's start date")
            other.valid_to = version.valid_from - dt.timedelta(days=1)
        if other.status == VersionStatus.PUBLISHED:
            other.status = VersionStatus.SUPERSEDED
        if (other.status, other.valid_to) != before:
            other.superseded_by_version_id = version.schedule_version_id
            other.prior_status, other.prior_valid_to = before
    if change_reason:
        version.change_reason = change_reason
    version.status = VersionStatus.PUBLISHED
    version.published_at = dt.datetime.utcnow()
    version.published_by = user.id
    schedule.status = ScheduleStatus.PUBLISHED
    schedule.updated_by = user.id
    db.flush()
    return result


def unpublish(db: Session, version: ScheduleVersion, user):
    """Turn the live version back into a draft and restore whatever its publishing closed."""
    if version.status != VersionStatus.PUBLISHED:
        bad(409, "Only the live (published) version can be unpublished")
    if db.query(TripSheet).filter(TripSheet.schedule_version_id == version.schedule_version_id).first():
        bad(409, "Trip sheets already use this version - it can no longer be unpublished")
    schedule = version.schedule
    draft = next((v for v in schedule.versions if v.status == VersionStatus.DRAFT), None)
    if draft:
        bad(409, f"Draft v{draft.version_number} already exists - delete it before unpublishing")
    vid = version.schedule_version_id
    restored = [v for v in schedule.versions if v.superseded_by_version_id == vid]
    for v in restored:
        v.status, v.valid_to = v.prior_status, v.prior_valid_to
    if not restored:  # published before this bookkeeping existed: reopen the version it replaced
        prev = [v for v in schedule.versions if v.status == VersionStatus.SUPERSEDED
                and v.version_number < version.version_number
                and v.valid_to == version.valid_from - dt.timedelta(days=1)]
        if prev:
            prev[-1].status, prev[-1].valid_to = VersionStatus.PUBLISHED, version.valid_to
    for v in schedule.versions:
        if v.superseded_by_version_id == vid:
            v.superseded_by_version_id = v.prior_status = v.prior_valid_to = None
    version.status = VersionStatus.DRAFT
    version.published_at = version.published_by = None
    if schedule.status == ScheduleStatus.PUBLISHED and not any(
            v.status == VersionStatus.PUBLISHED for v in schedule.versions):
        schedule.status = ScheduleStatus.DRAFT
    schedule.updated_by = user.id
    db.flush()


# --------------------------------------------------------------------------
# Timeline / print
# --------------------------------------------------------------------------
def version_for_date(schedule: BusSchedule, on: dt.date) -> ScheduleVersion | None:
    if on < schedule.effective_from or (schedule.effective_to and on > schedule.effective_to):
        return None
    for v in sorted(schedule.versions, key=lambda x: x.version_number, reverse=True):
        if v.status == VersionStatus.DRAFT:
            continue
        if v.valid_from <= on and (v.valid_to is None or on <= v.valid_to):
            return v
    return None


def _loc(l: Location):
    return {"location_id": l.location_id, "code": l.location_code, "name": l.location_name}


def build_timeline(version: ScheduleVersion, operating_date: dt.date) -> dict:
    tz = version.schedule.timezone
    rows = []
    for a in sorted(version.activities, key=lambda a: a.sequence_number):
        start = to_datetime(operating_date, a.start_day_offset, a.scheduled_start_time, tz)
        end = to_datetime(operating_date, a.end_day_offset, a.scheduled_end_time, tz)
        s, e = activity_span(a)
        row = {
            "activity_id": a.activity_id, "sequence_number": a.sequence_number, "activity_type": a.activity_type,
            "origin": _loc(a.origin), "destination": _loc(a.destination),
            "start": start.isoformat(), "end": end.isoformat(),
            "start_date": start.date().isoformat(), "end_date": end.date().isoformat(),
            "start_time": a.scheduled_start_time.strftime("%H:%M"), "end_time": a.scheduled_end_time.strftime("%H:%M"),
            "start_day_offset": a.start_day_offset, "end_day_offset": a.end_day_offset,
            "start_min": s, "end_min": e,
            "duration_minutes": int((end - start).total_seconds() // 60),
            "remarks": a.remarks, "distance_km": float(activity_km(a)),
        }
        if a.trip:
            t = a.trip
            row["trip"] = {
                "trip_number": t.trip_number, "route_code": t.route.route_code, "route_name": t.route.route_name,
                "direction_code": t.direction.direction_code, "direction_name": t.direction.direction_name,
                "planned_distance_km": float(t.planned_distance_km),
                "start_soc": _f(t.planned_start_soc_pct), "end_soc": _f(t.planned_end_soc_pct),
                "stops": [{
                    "scheduled_stop_time_id": st.scheduled_stop_time_id, "route_stop_id": st.route_stop_id,
                    "stop_sequence": st.stop_sequence, "location": _loc(st.route_stop.location),
                    "arrival": _hhmm(st.scheduled_arrival_time), "arrival_day_offset": st.arrival_day_offset,
                    "departure": _hhmm(st.scheduled_departure_time), "departure_day_offset": st.departure_day_offset,
                    "arrival_date": _date(operating_date, st.arrival_day_offset, st.scheduled_arrival_time),
                    "departure_date": _date(operating_date, st.departure_day_offset, st.scheduled_departure_time),
                    "soc": _f(st.planned_soc_pct),
                    "cumulative_km": float(st.route_stop.cumulative_distance_km),
                } for st in sorted(a.stop_times, key=lambda x: x.stop_sequence)],
            }
        if a.movement:
            m = a.movement
            row["movement"] = {
                "movement_purpose": m.movement_purpose, "payability_status": m.payability_status,
                "payment_basis": m.payment_basis, "planned_distance_km": float(m.planned_distance_km),
                "start_soc": _f(m.planned_start_soc_pct), "end_soc": _f(m.planned_end_soc_pct)}
        if a.charging:
            c = a.charging
            row["charging"] = {"charging_location": _loc(c.charging_location), "start_soc": _f(c.planned_start_soc_pct),
                               "end_soc": _f(c.planned_end_soc_pct), "expected_energy_kwh": _f(c.expected_energy_kwh)}
        if a.layover:
            l = a.layover
            row["layover"] = {"location": _loc(l.location), "layover_purpose": l.layover_purpose,
                              "start_soc": _f(l.planned_start_soc_pct), "end_soc": _f(l.planned_end_soc_pct)}
        if a.halt:
            hl = a.halt
            row["halt"] = {"location": _loc(hl.location), "start_soc": _f(hl.planned_start_soc_pct),
                           "end_soc": _f(hl.planned_end_soc_pct)}
        rows.append(row)
    sched = version.schedule
    return {
        "schedule_id": sched.schedule_id, "schedule_code": sched.schedule_code, "schedule_name": sched.schedule_name,
        "timezone": sched.timezone, "vehicle": {"vehicle_id": sched.vehicle.vehicle_id, "fleet_number": sched.vehicle.fleet_number,
                                                 "registration_number": sched.vehicle.registration_number},
        "schedule_version_id": version.schedule_version_id, "version_number": version.version_number,
        "version_status": version.status, "valid_from": version.valid_from.isoformat(),
        "valid_to": version.valid_to.isoformat() if version.valid_to else None,
        "operating_date": operating_date.isoformat(), "activities": rows, "summary": summarize(version),
    }


def _f(v):
    return float(v) if v is not None else None


def _hhmm(t):
    return t.strftime("%H:%M") if t else None


def _date(op, offset, t):
    return (op + dt.timedelta(days=offset or 0)).isoformat() if t else None
