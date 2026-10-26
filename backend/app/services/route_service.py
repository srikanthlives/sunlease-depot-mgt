from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.models import Location, RouteDirection, RouteStop, ScheduledStopTime
from app.schemas.schemas import StopIn


def replace_stops(db: Session, direction: RouteDirection, stops: list[StopIn]) -> RouteDirection:
    """Replace the whole ordered stop list. Validates terminals, recomputes
    cumulative distances and the direction total. Stops already used by a
    schedule timetable can only be edited in place (same locations, same order)."""
    if len(stops) < 2:
        raise HTTPException(422, "A direction needs at least two stops (origin and destination)")
    ids = [s.location_id for s in stops]
    found = {l.location_id: l for l in db.query(Location).filter(Location.location_id.in_(set(ids))).all()}
    company = direction.route.cost_center.company_id if direction.route.cost_center else None
    if company is not None:
        found = {i: l for i, l in found.items() if l.company_id == company}
    missing = set(ids) - set(found)
    if missing:
        raise HTTPException(422, f"Unknown location id(s): {sorted(missing)}")
    if ids[0] != direction.start_terminal_id:
        raise HTTPException(422, "The first stop must be the direction's start terminal")
    if ids[-1] != direction.end_terminal_id:
        raise HTTPException(422, "The last stop must be the direction's end terminal")
    if stops[0].distance_from_previous_km != 0:
        raise HTTPException(422, "Distance from previous for the first stop must be 0")
    inactive = [found[i].location_name for i in set(ids) if not found[i].is_active]
    if inactive:
        raise HTTPException(422, f"Inactive location(s): {', '.join(sorted(inactive))}")

    existing = list(direction.stops)
    in_place = len(existing) == len(stops) and all(e.location_id == s.location_id for e, s in zip(existing, stops))
    if not in_place:
        used = db.query(ScheduledStopTime.scheduled_stop_time_id).filter(
            ScheduledStopTime.route_stop_id.in_([e.route_stop_id for e in existing] or [-1])).first()
        if used:
            raise HTTPException(409, "This direction's stops are used by schedule timetables; only distances can be changed. "
                                     "Create a new direction for a different stop list.")
    running = Decimal(0)
    if in_place:
        for e, s in zip(existing, stops):
            running += s.distance_from_previous_km
            e.distance_from_previous_km = s.distance_from_previous_km
            e.cumulative_distance_km = running
            e.is_pickup_dropoff_stop = s.is_pickup_dropoff_stop
    else:
        for e in existing:
            db.delete(e)
        db.flush()
        for i, s in enumerate(stops, start=1):
            running += s.distance_from_previous_km
            db.add(RouteStop(direction_id=direction.direction_id, stop_sequence=i, location_id=s.location_id,
                             distance_from_previous_km=s.distance_from_previous_km, cumulative_distance_km=running,
                             is_pickup_dropoff_stop=s.is_pickup_dropoff_stop))
    direction.total_distance_km = running
    db.flush()
    db.refresh(direction)
    return direction
