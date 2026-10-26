"""Seed users, and (optionally) a small clearly-labelled SAMPLE dataset.

    python -m app.seed            # users + sample data
    python -m app.seed --users    # users only

Default logins (change them after first login):
    admin / Admin@123   scheduler / Scheduler@123   publisher / Publisher@123   viewer / Viewer@123
"""
import datetime as dt
import sys
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.migrate import migrate
from app.models.enums import Role
from app.models.models import Employee, Location, Route, RouteDirection, User, UserCostCenterRole, Vehicle
from app.schemas.schemas import (
    ActivityIn, ChargingIn, DirectionIn, LayoverIn, MovementIn, StopIn, StopTimeIn, TripIn,
)
from app.services import route_service
from app.services.org_service import default_cost_center
from app.services import schedule_service as svc

# admin is the super admin; the others get their role in the default cost center
USERS = [("admin", "System Admin", "Admin@123", Role.SUPER_ADMIN), ("scheduler", "Depot Scheduler", "Scheduler@123", Role.SCHEDULER),
         ("publisher", "Depot Manager", "Publisher@123", Role.PUBLISHER), ("viewer", "Viewer", "Viewer@123", Role.VIEWER)]


def seed_users(db: Session):
    cc = default_cost_center(db)
    for username, name, pw, role in USERS:
        if db.query(User).filter(User.username == username).first():
            continue
        u = User(username=username, full_name=name, hashed_password=hash_password(pw),
                 role=Role.SUPER_ADMIN if role == Role.SUPER_ADMIN else Role.USER)
        if role != Role.SUPER_ADMIN:
            u.cost_center_roles = [UserCostCenterRole(cost_center_id=cc.cost_center_id, role=role)]
        db.add(u)
    db.commit()


def T(s: str) -> dt.time:
    h, m = s.split(":")
    return dt.time(int(h), int(m))


def seed_sample(db: Session):
    if db.query(Location).filter(Location.location_code == "DEP01").first():
        print("[SEED] sample data already present - skipping")
        return
    cc = default_cost_center(db)
    L = {}
    for code, name, typ, chg in [("DEP01", "Sample Depot", "DEPOT", True), ("TRM-A", "Airport Terminal", "TERMINAL", False),
                                 ("S1", "Tech Park", "BUS_STOP", False), ("S2", "Metro Station", "BUS_STOP", False),
                                 ("TRM-B", "City Centre Terminal", "TERMINAL", False),
                                 ("CHG01", "Fast Charging Hub", "CHARGING_POINT", True)]:
        L[code] = Location(location_code=code, location_name=name, location_type=typ, supports_charging=chg,
                           company_id=cc.company_id)
        db.add(L[code])
    db.flush()
    bus = Vehicle(fleet_number="EV-101", registration_number="KA01-SAMPLE-101", battery_capacity_kwh=300,
                  home_depot_id=L["DEP01"].location_id, cost_center_id=cc.cost_center_id)
    db.add(bus)
    route = Route(route_code="R1", route_name="Airport - City Centre (sample)", cost_center_id=cc.cost_center_id)
    db.add(route)
    db.flush()
    up = RouteDirection(route_id=route.route_id, direction_code="UPSTREAM", direction_name="Airport to City Centre",
                        start_terminal_id=L["TRM-A"].location_id, end_terminal_id=L["TRM-B"].location_id)
    down = RouteDirection(route_id=route.route_id, direction_code="DOWNSTREAM", direction_name="City Centre to Airport",
                          start_terminal_id=L["TRM-B"].location_id, end_terminal_id=L["TRM-A"].location_id)
    db.add_all([up, down])
    db.flush()
    route_service.replace_stops(db, up, [StopIn(location_id=L[c].location_id, distance_from_previous_km=Decimal(d))
                                         for c, d in [("TRM-A", 0), ("S1", 6), ("S2", 7), ("TRM-B", 5)]])
    route_service.replace_stops(db, down, [StopIn(location_id=L[c].location_id, distance_from_previous_km=Decimal(d))
                                           for c, d in [("TRM-B", 0), ("S2", "5.5"), ("S1", 7), ("TRM-A", 6)]])
    today = dt.date.today()
    db.add_all([
        Employee(employee_number="D001", full_name="Sample Driver One", designation="Driver", staff_type="DRIVER",
                 home_depot_id=L["DEP01"].location_id, start_date=dt.date(2025, 4, 1), source="MANUAL", cost_center_id=cc.cost_center_id),
        Employee(employee_number="D002", full_name="Sample Driver Two", designation="Driver", staff_type="DRIVER",
                 home_depot_id=L["DEP01"].location_id, start_date=dt.date(2025, 6, 1), end_date=today + dt.timedelta(days=60),
                 source="MANUAL", cost_center_id=cc.cost_center_id),
        Employee(employee_number="C001", full_name="Sample Conductor", designation="Conductor", staff_type="CONDUCTOR",
                 home_depot_id=L["DEP01"].location_id, start_date=dt.date(2025, 4, 1), source="MANUAL", cost_center_id=cc.cost_center_id),
        Employee(employee_number="M001", full_name="Sample Charging Technician", designation="Technician",
                 staff_type="DEPOT_STAFF", home_depot_id=L["DEP01"].location_id, start_date=dt.date(2025, 1, 1), source="MANUAL", cost_center_id=cc.cost_center_id),
    ])
    from app.models.models import BusSchedule, ScheduleVersion
    admin = db.query(User).filter(User.username == "admin").first()
    sch = BusSchedule(schedule_code="SCH-101", schedule_name="EV-101 daily cycle (sample)", vehicle_id=bus.vehicle_id,
                      effective_from=today, created_by=admin.id, updated_by=admin.id,
                      cost_center_id=cc.cost_center_id)
    db.add(sch)
    db.flush()
    ver = ScheduleVersion(schedule_id=sch.schedule_id, version_number=1, valid_from=today, created_by=admin.id)
    db.add(ver)
    db.flush()

    soc = Decimal(100)
    seq = [0]

    def nxt():
        seq[0] += 1
        return seq[0]

    def move(o, d, s, e, km, purpose, pay, basis="UNSPECIFIED", eo=0):
        nonlocal soc
        ss = soc
        soc -= Decimal(km) * Decimal("0.4")
        svc.add_activity(db, ver, ActivityIn(
            sequence_number=nxt(), activity_type="NON_REVENUE_MOVEMENT", origin_location_id=L[o].location_id,
            destination_location_id=L[d].location_id, scheduled_start_time=T(s), scheduled_end_time=T(e),
            end_day_offset=eo, movement=MovementIn(
                movement_purpose=purpose, planned_distance_km=km,
                planned_start_soc_pct=ss, planned_end_soc_pct=soc, payability_status=pay, payment_basis=basis)))

    def layover(loc, s, e, purpose="INTER_TRIP", so=0, eo=0):
        svc.add_activity(db, ver, ActivityIn(
            sequence_number=nxt(), activity_type="LAYOVER", origin_location_id=L[loc].location_id,
            destination_location_id=L[loc].location_id, start_day_offset=so, scheduled_start_time=T(s),
            end_day_offset=eo, scheduled_end_time=T(e), layover=LayoverIn(location_id=L[loc].location_id, layover_purpose=purpose)))

    def charge(loc, s, e, to_soc, so=0, eo=0):
        nonlocal soc
        start_soc, soc = soc, Decimal(to_soc)
        svc.add_activity(db, ver, ActivityIn(
            sequence_number=nxt(), activity_type="CHARGING", origin_location_id=L[loc].location_id,
            destination_location_id=L[loc].location_id, start_day_offset=so, scheduled_start_time=T(s),
            end_day_offset=eo, scheduled_end_time=T(e),
            charging=ChargingIn(charging_location_id=L[loc].location_id, planned_start_soc_pct=start_soc,
                                planned_end_soc_pct=soc)))

    def trip(no, direction, times):
        nonlocal soc
        stops = list(direction.stops)
        total = direction.total_distance_km
        ss = soc
        st_in = []
        for rs, (arr, dep) in zip(stops, times):
            frac = rs.cumulative_distance_km
            st_in.append(StopTimeIn(route_stop_id=rs.route_stop_id, stop_sequence=rs.stop_sequence,
                                    arrival_day_offset=0 if arr else None, scheduled_arrival_time=T(arr) if arr else None,
                                    departure_day_offset=0 if dep else None, scheduled_departure_time=T(dep) if dep else None,
                                    planned_soc_pct=ss - frac * Decimal("0.8")))
        soc = ss - total * Decimal("0.8")
        svc.add_activity(db, ver, ActivityIn(
            sequence_number=nxt(), activity_type="PASSENGER_TRIP", origin_location_id=direction.start_terminal_id,
            destination_location_id=direction.end_terminal_id, scheduled_start_time=T(times[0][1]),
            scheduled_end_time=T(times[-1][0]), trip=TripIn(
                trip_number=no, route_id=route.route_id, direction_id=direction.direction_id, planned_distance_km=total,
                planned_start_soc_pct=ss,
                planned_end_soc_pct=soc, stops=st_in)))

    move("DEP01", "TRM-A", "05:00", "05:40", 10, "DEPOT_POSITIONING", "NON_PAYABLE", "INCLUDED_IN_CONTRACT")
    layover("TRM-A", "05:40", "06:00", "TERMINAL_RECOVERY")
    trip("T1", up, [(None, "06:00"), ("06:18", "06:20"), ("06:40", "06:41"), ("06:55", None)])
    layover("TRM-B", "06:55", "07:10")
    trip("T2", down, [(None, "07:10"), ("07:28", "07:30"), ("07:50", "07:51"), ("08:05", None)])
    move("TRM-A", "CHG01", "08:05", "08:30", 6, "CHARGING_ACCESS", "TO_BE_CONFIRMED")
    charge("CHG01", "08:30", "10:30", 90)
    move("CHG01", "TRM-A", "10:30", "10:55", 6, "RETURN_TO_SERVICE", "TO_BE_CONFIRMED")
    layover("TRM-A", "10:55", "11:00", "TERMINAL_RECOVERY")
    trip("T3", up, [(None, "11:00"), ("11:18", "11:20"), ("11:40", "11:41"), ("11:55", None)])
    layover("TRM-B", "11:55", "12:10")
    trip("T4", down, [(None, "12:10"), ("12:28", "12:30"), ("12:50", "12:51"), ("13:05", None)])
    layover("TRM-A", "13:05", "17:00")
    trip("T5", up, [(None, "17:00"), ("17:20", "17:22"), ("17:42", "17:43"), ("17:58", None)])
    layover("TRM-B", "17:58", "18:10")
    trip("T6", down, [(None, "18:10"), ("18:30", "18:32"), ("18:52", "18:53"), ("19:08", None)])
    move("TRM-A", "DEP01", "19:08", "19:45", 10, "RETURN_TO_DEPOT", "NON_PAYABLE", "INCLUDED_IN_CONTRACT")
    charge("DEP01", "19:45", "02:15", 100, eo=1)
    layover("DEP01", "02:15", "04:30", "OVERNIGHT_PARKING", so=1, eo=1)
    db.commit()
    print("[SEED] sample masters + draft schedule SCH-101 created (publish it from the UI, or use --publish)")


if __name__ == "__main__":
    migrate()
    with SessionLocal() as session:
        seed_users(session)
        if "--users" not in sys.argv:
            seed_sample(session)
            if "--publish" in sys.argv:
                from app.models.models import ScheduleVersion
                v = session.query(ScheduleVersion).first()
                admin_user = session.query(User).filter(User.username == "admin").first()
                svc.publish(session, v, admin_user, "Initial sample", True)
                session.commit()
                print("[SEED] SCH-101 v1 published")
    print("[SEED] done")
