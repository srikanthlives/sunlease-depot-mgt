import os
import tempfile

# Must be set before the app is imported.
_tmp = tempfile.mkdtemp()
os.environ["DEPOT_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db.session import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.migrate import migrate  # noqa: E402
from app.seed import seed_users  # noqa: E402


@pytest.fixture()
def db():
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as c:
        for t in ("lock_scheduled_activities_insert",):
            pass
    migrate()
    with SessionLocal() as s:
        seed_users(s)
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def client(db):
    return TestClient(app)


def login(client, username, password, cost_center_id=None):
    """Auth headers, working in `cost_center_id` (default: the user's first cost center)."""
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    ccs = r.json()["cost_centers"]
    cc = cost_center_id or (ccs[0]["cost_center_id"] if ccs else None)
    if cc is not None:
        h["X-Cost-Center-Id"] = str(cc)
    return h


@pytest.fixture()
def admin(client):
    return login(client, "admin", "Admin@123")


@pytest.fixture()
def world(client, admin):
    """Masters: depot, two terminals, a stop, charger, bus, route with both directions."""
    def post(url, body):
        r = client.post(url, json=body, headers=admin)
        assert r.status_code in (200, 201), (url, r.text)
        return r.json()
    loc = {}
    for code, typ, chg in [("DEP", "DEPOT", True), ("TA", "TERMINAL", False), ("MID", "BUS_STOP", False),
                           ("TB", "TERMINAL", False), ("CHG", "CHARGING_POINT", True)]:
        loc[code] = post("/api/locations", {"location_code": code, "location_name": code, "location_type": typ,
                                            "supports_charging": chg})["location_id"]
    bus = post("/api/vehicles", {"fleet_number": "B1", "registration_number": "R-B1", "home_depot_id": loc["DEP"]})
    bus2 = post("/api/vehicles", {"fleet_number": "B2", "registration_number": "R-B2", "home_depot_id": loc["DEP"]})
    route = post("/api/routes", {"route_code": "R1", "route_name": "Route 1"})
    up = post(f"/api/routes/{route['route_id']}/directions", {
        "direction_code": "UP", "direction_name": "Up", "start_terminal_id": loc["TA"], "end_terminal_id": loc["TB"]})
    down = post(f"/api/routes/{route['route_id']}/directions", {
        "direction_code": "DOWN", "direction_name": "Down", "start_terminal_id": loc["TB"], "end_terminal_id": loc["TA"]})
    up = post(f"/api/directions/{up['direction_id']}/stops", {"stops": [
        {"location_id": loc["TA"]}, {"location_id": loc["MID"], "distance_from_previous_km": 4},
        {"location_id": loc["TB"], "distance_from_previous_km": 6}]})
    down = post(f"/api/directions/{down['direction_id']}/stops", {"stops": [
        {"location_id": loc["TB"]}, {"location_id": loc["MID"], "distance_from_previous_km": 6.5},
        {"location_id": loc["TA"], "distance_from_previous_km": 4}]})
    return {"loc": loc, "bus": bus, "bus2": bus2, "route": route, "up": up, "down": down, "post": post,
            "client": client, "h": admin}


def make_schedule(w, code="S1", bus_key="bus", **kw):
    body = {"schedule_code": code, "schedule_name": code, "vehicle_id": w[bus_key]["vehicle_id"],
            "effective_from": "2026-11-01", **kw}
    s = w["post"]("/api/schedules", body)
    return s, s["versions"][0]["schedule_version_id"]


def trip_body(w, direction, number, start, mid_arr, mid_dep, end, start_off=0, end_off=0, km=None, seq=None):
    d = w[direction]
    km = km if km is not None else float(d["total_distance_km"])
    stops = d["stops"]
    mo = 0 if mid_arr >= start else 1
    body = {
        "activity_type": "PASSENGER_TRIP", "origin_location_id": d["start_terminal_id"],
        "destination_location_id": d["end_terminal_id"], "start_day_offset": start_off,
        "scheduled_start_time": start, "end_day_offset": end_off, "scheduled_end_time": end,
        "trip": {"trip_number": number, "route_id": d["route_id"], "direction_id": d["direction_id"],
                 "planned_distance_km": km, "stops": [
                     {"route_stop_id": stops[0]["route_stop_id"], "stop_sequence": 1,
                      "departure_day_offset": start_off, "scheduled_departure_time": start},
                     {"route_stop_id": stops[1]["route_stop_id"], "stop_sequence": 2,
                      "arrival_day_offset": start_off + (1 if mid_arr < start else 0), "scheduled_arrival_time": mid_arr,
                      "departure_day_offset": start_off + (1 if mid_dep < start else 0), "scheduled_departure_time": mid_dep},
                     {"route_stop_id": stops[2]["route_stop_id"], "stop_sequence": 3,
                      "arrival_day_offset": end_off, "scheduled_arrival_time": end}]}}
    if seq:
        body["sequence_number"] = seq
    return body


def add(w, version_id, body):
    r = w["client"].post(f"/api/schedule-versions/{version_id}/activities", json=body, headers=w["h"])
    return r


def validate(w, version_id):
    r = w["client"].post(f"/api/schedule-versions/{version_id}/validate", headers=w["h"])
    assert r.status_code == 200, r.text
    return r.json()


def codes(result, severity=None):
    return {i["code"] for i in result["issues"] if severity is None or i["severity"] == severity}
