import datetime as dt

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import deps
from app.core.access import Scope, scope
from app.db.session import get_db
from app.models.enums import Role, VersionStatus
from app.models.models import (
    BusSchedule, Employee, EmployeeAvailability, Location, Route, RouteDirection, ScheduledCharging, ScheduledTrip,
    ScheduleVersion, User, Vehicle,
)
from app.schemas import schemas as S
from app.services import audit_service, availability_service, employee_service, route_service, settings_service

router = APIRouter(prefix="/api", tags=["masters"])


def _commit(db: Session, what: str):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, f"{what} conflicts with an existing record: {str(exc.orig)[:160]}")


def _company_location(db: Session, location_id: int | None, company_id: int, what: str = "Location"):
    """A location used by a cost-center record must belong to that cost center's company."""
    if location_id is None:
        return None
    loc = db.get(Location, location_id)
    if loc is None or loc.company_id != company_id:
        raise HTTPException(422, f"{what} {location_id} does not exist in this company")
    return loc


def _cc_company(sc: Scope, cost_center_id: int) -> int:
    from app.models.models import CostCenter
    return sc.companies.get(cost_center_id) or sc.db.get(CostCenter, cost_center_id).company_id


# ---------------- locations (shared by the cost centers of one company) ----------------
@router.get("/locations", response_model=list[S.LocationOut])
def list_locations(q: str | None = None, location_type: str | None = None, charging_only: bool = False,
                   include_inactive: bool = True, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    query = db.query(Location).filter(Location.company_id.in_(sc.visible_companies))
    if q:
        like = f"%{q}%"
        query = query.filter((Location.location_code.ilike(like)) | (Location.location_name.ilike(like)))
    if location_type:
        query = query.filter(Location.location_type == location_type)
    if charging_only:
        query = query.filter(Location.supports_charging.is_(True))
    if not include_inactive:
        query = query.filter(Location.is_active.is_(True))
    return query.order_by(Location.location_name).all()


@router.post("/locations", response_model=S.LocationOut, status_code=201)
def create_location(body: S.LocationIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    company_id = sc.target_company(Role.SCHEDULER)
    loc = Location(**body.model_dump(), company_id=company_id)
    db.add(loc)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Location code {body.location_code} already exists")
    audit_service.record(db, sc.user, "CREATE", "Location", loc.location_id, body.model_dump())
    db.commit()
    return loc


def _get_location(db: Session, sc: Scope, location_id: int, minimum: str) -> Location:
    loc = db.get(Location, location_id)
    if not loc:
        raise HTTPException(404, "Location not found")
    sc.require_company(loc.company_id, minimum, "Location")
    return loc


@router.put("/locations/{location_id}", response_model=S.LocationOut)
def update_location(location_id: int, body: S.LocationIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    loc = _get_location(db, sc, location_id, Role.SCHEDULER)
    if body.supports_charging is False and loc.supports_charging:
        if db.query(ScheduledCharging).filter(ScheduledCharging.charging_location_id == location_id).first():
            raise HTTPException(409, "Charging is scheduled at this location - it cannot be marked as non-charging")
    for k, v in body.model_dump().items():
        setattr(loc, k, v)
    audit_service.record(db, sc.user, "UPDATE", "Location", location_id, body.model_dump())
    _commit(db, "Location")
    return loc


@router.delete("/locations/{location_id}", status_code=204)
def delete_location(location_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """Hard-delete only when nothing references it; otherwise the client should deactivate."""
    loc = _get_location(db, sc, location_id, Role.SCHEDULER)
    audit_service.record(db, sc.user, "DELETE", "Location", location_id, loc.location_code)
    try:
        db.delete(loc)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This location is referenced by routes, vehicles or schedules - deactivate it instead")


# ---------------- vehicles ----------------
def _vehicle_out(db: Session, v: Vehicle) -> dict:
    sched = (db.query(BusSchedule.schedule_code).join(ScheduleVersion)
             .filter(BusSchedule.vehicle_id == v.vehicle_id, ScheduleVersion.status == VersionStatus.PUBLISHED)
             .distinct().all())
    in_use = db.query(BusSchedule.schedule_id).filter(BusSchedule.vehicle_id == v.vehicle_id).first() is not None
    return {**S.VehicleIn.model_validate(v, from_attributes=True).model_dump(), "vehicle_id": v.vehicle_id,
            "cost_center_id": v.cost_center_id,
            "home_depot_code": v.home_depot.location_code if v.home_depot else None,
            "home_depot_name": v.home_depot.location_name if v.home_depot else None,
            "assigned_schedules": sorted(s[0] for s in sched), "in_use": in_use}


def _get_vehicle(db: Session, sc: Scope, vehicle_id: int, minimum: str) -> Vehicle:
    v = db.get(Vehicle, vehicle_id)
    if not v:
        raise HTTPException(404, "Vehicle not found")
    sc.require(v.cost_center_id, minimum, "Vehicle")
    return v


@router.get("/vehicles", response_model=list[S.VehicleOut])
def list_vehicles(q: str | None = None, status: str | None = None, home_depot_id: int | None = None,
                  db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    query = sc.filter(db.query(Vehicle), Vehicle.cost_center_id)
    if q:
        like = f"%{q}%"
        query = query.filter((Vehicle.fleet_number.ilike(like)) | (Vehicle.registration_number.ilike(like)))
    if status:
        query = query.filter(Vehicle.status == status)
    if home_depot_id:
        query = query.filter(Vehicle.home_depot_id == home_depot_id)
    return [_vehicle_out(db, v) for v in query.order_by(Vehicle.fleet_number).all()]


@router.post("/vehicles", response_model=S.VehicleOut, status_code=201)
def create_vehicle(body: S.VehicleIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    cc = sc.target(Role.SCHEDULER)
    _company_location(db, body.home_depot_id, sc.companies[cc], "Home depot")
    v = Vehicle(**body.model_dump(), cost_center_id=cc)
    db.add(v)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Fleet number or registration number already exists")
    audit_service.record(db, sc.user, "CREATE", "Vehicle", v.vehicle_id, body.model_dump())
    db.commit()
    return _vehicle_out(db, v)


@router.get("/vehicles/{vehicle_id}", response_model=S.VehicleOut)
def get_vehicle(vehicle_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    return _vehicle_out(db, _get_vehicle(db, sc, vehicle_id, Role.VIEWER))


@router.put("/vehicles/{vehicle_id}", response_model=S.VehicleOut)
def update_vehicle(vehicle_id: int, body: S.VehicleIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    v = _get_vehicle(db, sc, vehicle_id, Role.SCHEDULER)
    _company_location(db, body.home_depot_id, _cc_company(sc, v.cost_center_id), "Home depot")
    if body.status != "ACTIVE" and v.status == "ACTIVE" and _vehicle_out(db, v)["assigned_schedules"]:
        raise HTTPException(409, "Vehicle has published schedules - retire those schedules before deactivating the bus")
    for k, val in body.model_dump().items():
        setattr(v, k, val)
    audit_service.record(db, sc.user, "UPDATE", "Vehicle", vehicle_id, body.model_dump())
    _commit(db, "Vehicle")
    return _vehicle_out(db, v)


@router.delete("/vehicles/{vehicle_id}", status_code=204)
def delete_vehicle(vehicle_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    v = _get_vehicle(db, sc, vehicle_id, Role.SCHEDULER)
    codes = [s[0] for s in db.query(BusSchedule.schedule_code).filter(BusSchedule.vehicle_id == vehicle_id).all()]
    if codes:
        raise HTTPException(409, f"Bus is used by schedule(s) {', '.join(sorted(codes))} - deactivate it instead")
    audit_service.record(db, sc.user, "DELETE", "Vehicle", vehicle_id, v.fleet_number)
    db.delete(v)
    _commit(db, "Vehicle")


# ---------------- routes / directions / stops ----------------
def _direction_out(d: RouteDirection) -> dict:
    return {
        "direction_id": d.direction_id, "route_id": d.route_id, "direction_code": d.direction_code,
        "direction_name": d.direction_name, "start_terminal_id": d.start_terminal_id,
        "end_terminal_id": d.end_terminal_id, "start_terminal_name": d.start_terminal.location_name,
        "end_terminal_name": d.end_terminal.location_name, "total_distance_km": d.total_distance_km,
        "is_active": d.is_active,
        "stops": [{"route_stop_id": s.route_stop_id, "stop_sequence": s.stop_sequence, "location_id": s.location_id,
                   "location_code": s.location.location_code, "location_name": s.location.location_name,
                   "distance_from_previous_km": s.distance_from_previous_km,
                   "cumulative_distance_km": s.cumulative_distance_km,
                   "is_pickup_dropoff_stop": s.is_pickup_dropoff_stop} for s in d.stops],
    }


def _route_schedules(db: Session, route_id: int) -> list[str]:
    rows = (db.query(BusSchedule.schedule_code).join(ScheduleVersion).join(ScheduledTrip,
            ScheduledTrip.schedule_version_id == ScheduleVersion.schedule_version_id)
            .filter(ScheduledTrip.route_id == route_id).distinct().all())
    return sorted(r[0] for r in rows)


def _route_out(r: Route, in_use: bool = False) -> dict:
    return {"route_id": r.route_id, "cost_center_id": r.cost_center_id, "route_code": r.route_code,
            "route_name": r.route_name, "description": r.description, "status": r.status, "in_use": in_use,
            "directions": [_direction_out(d) for d in r.directions]}


def _get_route(db: Session, sc: Scope, route_id: int, minimum: str) -> Route:
    r = db.get(Route, route_id)
    if not r:
        raise HTTPException(404, "Route not found")
    sc.require(r.cost_center_id, minimum, "Route")
    return r


def _get_direction(db: Session, sc: Scope, direction_id: int, minimum: str) -> RouteDirection:
    d = db.get(RouteDirection, direction_id)
    if not d:
        raise HTTPException(404, "Direction not found")
    sc.require(d.route.cost_center_id, minimum, "Direction")
    return d


def _check_terminals(db: Session, sc: Scope, route: Route, body: S.DirectionIn):
    company = _cc_company(sc, route.cost_center_id)
    for lid in (body.start_terminal_id, body.end_terminal_id):
        _company_location(db, lid, company)


@router.get("/routes", response_model=list[S.RouteOut])
def list_routes(q: str | None = None, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    query = sc.filter(db.query(Route), Route.cost_center_id)
    if q:
        like = f"%{q}%"
        query = query.filter((Route.route_code.ilike(like)) | (Route.route_name.ilike(like)))
    used = {x[0] for x in db.query(ScheduledTrip.route_id).distinct().all()}
    return [_route_out(r, r.route_id in used) for r in query.order_by(Route.route_code).all()]


@router.post("/routes", response_model=S.RouteOut, status_code=201)
def create_route(body: S.RouteIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    r = Route(**body.model_dump(), cost_center_id=sc.target(Role.SCHEDULER))
    db.add(r)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Route code {body.route_code} already exists")
    audit_service.record(db, sc.user, "CREATE", "Route", r.route_id, body.model_dump())
    db.commit()
    return _route_out(r)


@router.get("/routes/{route_id}", response_model=S.RouteOut)
def get_route(route_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    r = _get_route(db, sc, route_id, Role.VIEWER)
    return _route_out(r, bool(_route_schedules(db, route_id)))


@router.put("/routes/{route_id}", response_model=S.RouteOut)
def update_route(route_id: int, body: S.RouteIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    r = _get_route(db, sc, route_id, Role.SCHEDULER)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    audit_service.record(db, sc.user, "UPDATE", "Route", route_id, body.model_dump())
    _commit(db, "Route")
    return _route_out(r, bool(_route_schedules(db, route_id)))


@router.delete("/routes/{route_id}", status_code=204)
def delete_route(route_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """Deletes the route with its directions and stops, only when no schedule has trips on it."""
    r = _get_route(db, sc, route_id, Role.SCHEDULER)
    codes = _route_schedules(db, route_id)
    if codes:
        raise HTTPException(409, f"Route is used by schedule(s) {', '.join(codes)} - set it inactive instead")
    audit_service.record(db, sc.user, "DELETE", "Route", route_id, r.route_code)
    for d in r.directions:
        db.delete(d)
    db.flush()
    db.delete(r)
    _commit(db, "Route")


@router.get("/routes/{route_id}/directions", response_model=list[S.DirectionOut])
def list_directions(route_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    return [_direction_out(d) for d in _get_route(db, sc, route_id, Role.VIEWER).directions]


@router.post("/routes/{route_id}/directions", response_model=S.DirectionOut, status_code=201)
def create_direction(route_id: int, body: S.DirectionIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    route = _get_route(db, sc, route_id, Role.SCHEDULER)
    _check_terminals(db, sc, route, body)
    if body.start_terminal_id == body.end_terminal_id:
        raise HTTPException(422, "Start and end terminals must be different")
    d = RouteDirection(route_id=route_id, **body.model_dump())
    db.add(d)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"Direction code {body.direction_code} already exists on this route")
    audit_service.record(db, sc.user, "CREATE", "RouteDirection", d.direction_id, body.model_dump())
    db.commit()
    return _direction_out(d)


@router.put("/directions/{direction_id}", response_model=S.DirectionOut)
def update_direction(direction_id: int, body: S.DirectionIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    d = _get_direction(db, sc, direction_id, Role.SCHEDULER)
    _check_terminals(db, sc, d.route, body)
    terminals_changed = (d.start_terminal_id, d.end_terminal_id) != (body.start_terminal_id, body.end_terminal_id)
    if terminals_changed and d.stops:
        raise HTTPException(409, "Terminals cannot change once stops exist - rebuild the stop list in a new direction")
    for k, v in body.model_dump().items():
        setattr(d, k, v)
    audit_service.record(db, sc.user, "UPDATE", "RouteDirection", direction_id, body.model_dump())
    _commit(db, "Direction")
    return _direction_out(d)


@router.get("/directions/{direction_id}/stops", response_model=list[S.StopOut])
def list_stops(direction_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    return _direction_out(_get_direction(db, sc, direction_id, Role.VIEWER))["stops"]


@router.post("/directions/{direction_id}/stops", response_model=S.DirectionOut)
def replace_direction_stops(direction_id: int, body: S.StopsReplaceIn, db: Session = Depends(get_db),
                            sc: Scope = Depends(scope)):
    d = _get_direction(db, sc, direction_id, Role.SCHEDULER)
    route_service.replace_stops(db, d, body.stops)
    audit_service.record(db, sc.user, "UPDATE", "RouteStops", direction_id,
                         {"stops": len(body.stops), "total_km": d.total_distance_km})
    db.commit()
    return _direction_out(d)


# ---------------- employees ----------------
def _emp_out(e: Employee) -> dict:
    return {**S.EmployeeIn.model_validate(e, from_attributes=True).model_dump(), "employee_id": e.employee_id,
            "cost_center_id": e.cost_center_id, "source": e.source, "last_synced_at": e.last_synced_at,
            "home_depot_code": e.home_depot.location_code if e.home_depot else None,
            "home_depot_name": e.home_depot.location_name if e.home_depot else None}


@router.get("/employees", response_model=list[S.EmployeeOut])
def list_employees(q: str | None = None, staff_type: str | None = None, home_depot_id: int | None = None,
                   available_on: dt.date | None = None, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    query = sc.filter(db.query(Employee), Employee.cost_center_id)
    if q:
        like = f"%{q}%"
        query = query.filter((Employee.employee_number.ilike(like)) | (Employee.full_name.ilike(like)))
    if staff_type:
        query = query.filter(Employee.staff_type == staff_type)
    if home_depot_id:
        query = query.filter(Employee.home_depot_id == home_depot_id)
    if available_on:
        query = query.filter(Employee.status == "ACTIVE", Employee.start_date <= available_on,
                             (Employee.end_date.is_(None)) | (Employee.end_date >= available_on))
    return [_emp_out(e) for e in query.order_by(Employee.employee_number, Employee.start_date).all()]


@router.post("/employees", response_model=S.EmployeeOut, status_code=201)
def create_employee(body: S.EmployeeIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    cc = sc.target(Role.SCHEDULER)
    _company_location(db, body.home_depot_id, sc.companies[cc], "Home depot")
    employee_service.check_overlap(db, body.employee_number, body.start_date, body.end_date)
    e = Employee(**body.model_dump(), source="MANUAL", cost_center_id=cc)
    db.add(e)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An employee stint with this number and start date already exists")
    audit_service.record(db, sc.user, "CREATE", "Employee", e.employee_id, body.model_dump())
    db.commit()
    return _emp_out(e)


@router.put("/employees/{employee_id}", response_model=S.EmployeeOut)
def update_employee(employee_id: int, body: S.EmployeeIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    e = db.get(Employee, employee_id)
    if not e:
        raise HTTPException(404, "Employee not found")
    sc.require(e.cost_center_id, Role.SCHEDULER, "Employee")
    _company_location(db, body.home_depot_id, _cc_company(sc, e.cost_center_id), "Home depot")
    employee_service.check_overlap(db, body.employee_number, body.start_date, body.end_date, employee_id)
    for k, v in body.model_dump().items():
        setattr(e, k, v)
    audit_service.record(db, sc.user, "UPDATE", "Employee", employee_id, body.model_dump())
    _commit(db, "Employee")
    return _emp_out(e)


@router.get("/employees/{employee_id}/usage")
def employee_usage(employee_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """Where this employee is already used, so the UI knows whether a move or a stint split follows."""
    e = db.get(Employee, employee_id)
    if not e:
        raise HTTPException(404, "Employee not found")
    sc.require(e.cost_center_id, Role.VIEWER, "Employee")
    return {"employee_id": employee_id, "cost_center_id": e.cost_center_id,
            "used": employee_service.references(db, employee_id)}


@router.post("/employees/{employee_id}/transfer", response_model=S.EmployeeOut)
def transfer_employee(employee_id: int, body: S.EmployeeTransferIn, db: Session = Depends(get_db),
                      sc: Scope = Depends(scope)):
    """Put an employee in another cost center: a plain move while unused, otherwise a new stint."""
    e = db.get(Employee, employee_id)
    if not e:
        raise HTTPException(404, "Employee not found")
    sc.require(e.cost_center_id, Role.ADMIN, "Employee")
    sc.require(body.cost_center_id, Role.ADMIN, "Cost center")
    if sc.companies.get(e.cost_center_id) != sc.companies.get(body.cost_center_id):
        raise HTTPException(422, "An employee can only move between cost centers of the same company")
    result = employee_service.transfer(db, e, body.cost_center_id, body.effective_from, sc.user)
    audit_service.record(db, sc.user, "TRANSFER", "Employee", employee_id,
                         body.model_dump(mode="json") | {k: str(v) for k, v in result.items()})
    _commit(db, "Employee")
    return _emp_out(db.get(Employee, result["employee_id"]))


@router.get("/employees-template")
def employee_template(_: User = Depends(deps.get_current_user)):
    return Response(employee_service.template_bytes(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="employee_template.xlsx"'})


@router.post("/employees-import")
async def employee_import(file: UploadFile = File(...), db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    cc = sc.target(Role.SCHEDULER)
    result = employee_service.import_workbook(db, await file.read(), cc, sc.companies[cc])
    audit_service.record(db, sc.user, "IMPORT", "Employee", None, {k: result[k] for k in ("created", "updated")})
    db.commit()
    return result


@router.post("/employees-sync-hrms")
def employee_sync(db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    cc = sc.target(Role.SCHEDULER)
    result = employee_service.sync_from_hrms(db, cc, sc.companies[cc])
    audit_service.record(db, sc.user, "SYNC", "Employee", None, {k: result[k] for k in ("created", "updated")})
    db.commit()
    return result


# ---------------- employee availability register ----------------
def _avail_out(a: EmployeeAvailability) -> dict:
    return {**S.AvailabilityIn.model_validate(a, from_attributes=True).model_dump(),
            "availability_id": a.availability_id, "cost_center_id": a.cost_center_id,
            "employee_number": a.employee.employee_number if a.employee else None,
            "employee_name": a.employee.full_name if a.employee else None,
            "staff_type": a.employee.staff_type if a.employee else None}


def _avail_employee(db: Session, sc: Scope, employee_id: int, cc: int) -> Employee:
    e = db.get(Employee, employee_id)
    if e is None or e.cost_center_id != cc:
        raise HTTPException(422, f"Employee {employee_id} does not exist in this cost center")
    return e


@router.get("/employee-availability", response_model=list[S.AvailabilityOut])
def list_availability(employee_id: int | None = None, date_from: dt.date | None = None,
                      date_to: dt.date | None = None, status: str | None = None,
                      db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    query = sc.filter(db.query(EmployeeAvailability), EmployeeAvailability.cost_center_id)
    if employee_id:
        query = query.filter(EmployeeAvailability.employee_id == employee_id)
    if status:
        query = query.filter(EmployeeAvailability.status == status)
    # any entry touching the window, so a leave spanning its edges still shows
    if date_from:
        query = query.filter(EmployeeAvailability.to_date >= date_from)
    if date_to:
        query = query.filter(EmployeeAvailability.from_date <= date_to)
    rows = query.order_by(EmployeeAvailability.from_date.desc(), EmployeeAvailability.employee_id).all()
    return [_avail_out(a) for a in rows]


@router.post("/employee-availability", response_model=S.AvailabilityOut, status_code=201)
def create_availability(body: S.AvailabilityIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    cc = sc.target(Role.MIS)
    _avail_employee(db, sc, body.employee_id, cc)
    availability_service.check_overlap(db, body.employee_id, body.from_date, body.to_date)
    a = EmployeeAvailability(**body.model_dump(), cost_center_id=cc, created_by=sc.user.id)
    db.add(a)
    db.flush()
    audit_service.record(db, sc.user, "CREATE", "EmployeeAvailability", a.availability_id, body.model_dump())
    _commit(db, "Availability entry")
    return _avail_out(a)


@router.put("/employee-availability/{availability_id}", response_model=S.AvailabilityOut)
def update_availability(availability_id: int, body: S.AvailabilityIn, db: Session = Depends(get_db),
                        sc: Scope = Depends(scope)):
    a = db.get(EmployeeAvailability, availability_id)
    if not a:
        raise HTTPException(404, "Availability entry not found")
    sc.require(a.cost_center_id, Role.MIS, "Availability entry")
    _avail_employee(db, sc, body.employee_id, a.cost_center_id)
    availability_service.check_overlap(db, body.employee_id, body.from_date, body.to_date, availability_id)
    for k, v in body.model_dump().items():
        setattr(a, k, v)
    audit_service.record(db, sc.user, "UPDATE", "EmployeeAvailability", availability_id, body.model_dump())
    _commit(db, "Availability entry")
    return _avail_out(a)


@router.delete("/employee-availability/{availability_id}", status_code=204)
def delete_availability(availability_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    a = db.get(EmployeeAvailability, availability_id)
    if not a:
        raise HTTPException(404, "Availability entry not found")
    sc.require(a.cost_center_id, Role.MIS, "Availability entry")
    audit_service.record(db, sc.user, "DELETE", "EmployeeAvailability", availability_id,
                         {"employee_id": a.employee_id, "status": a.status,
                          "from_date": str(a.from_date), "to_date": str(a.to_date)})
    db.delete(a)
    db.commit()
    return Response(status_code=204)


@router.get("/employees-free-on")
def employees_free_on(on: dt.date, staff_type: str | None = None, db: Session = Depends(get_db),
                      sc: Scope = Depends(scope)):
    """Who can take a duty on `on`, and who cannot and why. Feeds the roster pickers."""
    query = sc.filter(db.query(Employee), Employee.cost_center_id)
    if staff_type:
        query = query.filter(Employee.staff_type == staff_type)
    free, busy = [], []
    for e in query.order_by(Employee.employee_number).all():
        ok, why = availability_service.free_on(db, e, on)
        item = {"employee_id": e.employee_id, "employee_number": e.employee_number,
                "employee_name": e.full_name, "staff_type": e.staff_type}
        if ok:
            free.append(item)
        elif availability_service.employed_on(e, on):
            busy.append({**item, "reason": why})
    return {"on": on, "free": free, "unavailable": busy}


# ---------------- settings (per cost center) ----------------
@router.get("/settings")
def get_settings(db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    cc = sc.target(Role.VIEWER)
    return {"cost_center_id": cc, "values": settings_service.get_all(db, cc),
            "descriptions": {k: d[1] for k, d in settings_service.DEFAULTS.items()}}


@router.put("/settings")
def put_settings(body: S.SettingsIn, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    cc = sc.target(Role.ADMIN)
    try:
        values = settings_service.update(db, cc, body.values)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    audit_service.record(db, sc.user, "UPDATE", "Settings", cc, body.values)
    db.commit()
    return {"values": values}
