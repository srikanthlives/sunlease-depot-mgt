"""Companies, cost centers, per-cost-center roles and data isolation."""
from .conftest import add, login, make_schedule, trip_body


def org(c, h):
    """A second company with two cost centers, plus a user who is PUBLISHER in one and VIEWER in another."""
    def post(url, body):
        r = c.post(url, json=body, headers=h)
        assert r.status_code == 201, r.text
        return r.json()
    co = post("/api/companies", {"company_code": "ACME", "company_name": "Acme Transit"})
    north = post("/api/cost-centers", {"company_id": co["company_id"], "cost_center_code": "NORTH", "cost_center_name": "North depot"})
    south = post("/api/cost-centers", {"company_id": co["company_id"], "cost_center_code": "SOUTH", "cost_center_name": "South depot"})
    post("/api/users", {"username": "ravi", "password": "Ravi@123", "cost_center_roles": [
        {"cost_center_id": north["cost_center_id"], "role": "PUBLISHER"},
        {"cost_center_id": south["cost_center_id"], "role": "VIEWER"}]})
    return co, north, south


def test_only_super_admin_manages_organisation(client, admin):
    co, north, south = org(client, admin)
    ravi = login(client, "ravi", "Ravi@123")
    assert client.get("/api/companies", headers=ravi).status_code == 403
    assert client.post("/api/cost-centers", json={"company_id": co["company_id"], "cost_center_code": "X",
                                                  "cost_center_name": "X"}, headers=ravi).status_code == 403
    assert client.get("/api/users", headers=ravi).status_code == 403
    # a cost center cannot move to another company (its locations belong to the company)
    r = client.put(f"/api/cost-centers/{north['cost_center_id']}", headers=admin,
                   json={"company_id": 1, "cost_center_code": "NORTH", "cost_center_name": "North"})
    assert r.status_code == 409


def test_user_switches_between_cost_centers_with_a_role_in_each(client, admin):
    co, north, south = org(client, admin)
    me = client.post("/api/auth/login", json={"username": "ravi", "password": "Ravi@123"}).json()
    assert {m["cost_center_code"]: m["role"] for m in me["cost_centers"]} == {"NORTH": "PUBLISHER", "SOUTH": "VIEWER"}
    in_north = login(client, "ravi", "Ravi@123", north["cost_center_id"])
    in_south = login(client, "ravi", "Ravi@123", south["cost_center_id"])
    bus = {"fleet_number": "N1", "registration_number": "R-N1"}
    assert client.post("/api/vehicles", json=bus, headers=in_north).status_code == 201
    assert client.post("/api/vehicles", json={**bus, "fleet_number": "S1", "registration_number": "R-S1"},
                       headers=in_south).status_code == 403                                  # viewer there
    # a cost center the user has no role in cannot even be selected
    other = {**in_north, "X-Cost-Center-Id": "1"}
    assert client.get("/api/vehicles", headers=other).status_code == 403


def test_cost_centers_are_isolated(world, client, admin):
    co, north, south = org(client, admin)
    s, vid = make_schedule(world)                                       # in the default cost center
    ravi = login(client, "ravi", "Ravi@123", north["cost_center_id"])
    assert client.get("/api/vehicles", headers=ravi).json() == []
    assert client.get("/api/schedules", headers=ravi).json() == []
    assert client.get("/api/locations", headers=ravi).json() == []      # other company's locations
    # direct access by id is "not found", reads and writes alike
    assert client.get(f"/api/schedules/{s['schedule_id']}", headers=ravi).status_code == 404
    assert client.get(f"/api/schedule-versions/{vid}", headers=ravi).status_code == 404
    assert client.put(f"/api/vehicles/{world['bus']['vehicle_id']}", headers=ravi,
                      json={"fleet_number": "B1", "registration_number": "R-B1"}).status_code == 404
    # cannot schedule another cost center's bus, or use another company's location
    r = client.post("/api/schedules", headers=ravi, json={"schedule_code": "X1", "schedule_name": "X",
                                                          "vehicle_id": world["bus"]["vehicle_id"], "effective_from": "2026-11-01"})
    assert r.status_code == 422
    r = client.post("/api/vehicles", headers=ravi, json={"fleet_number": "N2", "registration_number": "R-N2",
                                                        "home_depot_id": world["loc"]["DEP"]})
    assert r.status_code == 422


def test_locations_are_shared_within_a_company(client, admin):
    co, north, south = org(client, admin)
    in_north = {**admin, "X-Cost-Center-Id": str(north["cost_center_id"])}
    in_south = {**admin, "X-Cost-Center-Id": str(south["cost_center_id"])}
    r = client.post("/api/locations", headers=in_north, json={"location_code": "ACME-DEP", "location_name": "Acme depot",
                                                              "location_type": "DEPOT"})
    assert r.status_code == 201
    assert [l["location_code"] for l in client.get("/api/locations", headers=in_south).json()] == ["ACME-DEP"]
    # a bus in SOUTH can use the depot created from NORTH
    r = client.post("/api/vehicles", headers=in_south, json={"fleet_number": "S9", "registration_number": "R-S9",
                                                             "home_depot_id": r.json()["location_id"]})
    assert r.status_code == 201


def test_all_my_cost_centers_view_is_read_only(world, client, admin):
    co, north, south = org(client, admin)
    in_north = {**admin, "X-Cost-Center-Id": str(north["cost_center_id"])}
    assert client.post("/api/vehicles", headers=in_north, json={"fleet_number": "N1", "registration_number": "R-N1"}).status_code == 201
    everything = {**admin, "X-Cost-Center-Id": "all"}
    fleets = {v["fleet_number"]: v["cost_center_id"] for v in client.get("/api/vehicles", headers=everything).json()}
    assert set(fleets) == {"B1", "B2", "N1"} and fleets["N1"] == north["cost_center_id"]
    # creating needs a specific cost center
    assert client.post("/api/vehicles", headers=everything, json={"fleet_number": "Z", "registration_number": "Z"}).status_code == 422
    # ravi's "all" is just NORTH + SOUTH
    ravi_all = {**login(client, "ravi", "Ravi@123"), "X-Cost-Center-Id": "all"}
    assert [v["fleet_number"] for v in client.get("/api/vehicles", headers=ravi_all).json()] == ["N1"]
    # but editing a record opened from the all view uses the role in its own cost center
    n1 = next(v for v in client.get("/api/vehicles", headers=ravi_all).json())
    r = client.put(f"/api/vehicles/{n1['vehicle_id']}", headers=ravi_all,
                   json={"fleet_number": "N1", "registration_number": "R-N1", "battery_capacity_kwh": 300})
    assert r.status_code == 200


def test_settings_and_audit_are_per_cost_center(world, client, admin):
    co, north, south = org(client, admin)
    in_north = {**admin, "X-Cost-Center-Id": str(north["cost_center_id"])}
    assert client.put("/api/settings", json={"values": {"gap_warn_minutes": 5}}, headers=in_north).status_code == 200
    assert client.get("/api/settings", headers=in_north).json()["values"]["gap_warn_minutes"] == "5"
    assert client.get("/api/settings", headers=world["h"]).json()["values"]["gap_warn_minutes"] == "30"
    ravi = login(client, "ravi", "Ravi@123", north["cost_center_id"])
    assert client.put("/api/settings", json={"values": {"gap_warn_minutes": 9}}, headers=ravi).status_code == 403
    assert client.get("/api/audit-logs", headers=ravi).status_code == 403                    # publisher, not admin
    logs = client.get("/api/audit-logs", headers=in_north).json()
    assert logs and all(l["cost_center_id"] == north["cost_center_id"] for l in logs)


def test_trip_must_use_a_route_of_the_same_cost_center(world, client, admin):
    co, north, south = org(client, admin)
    in_north = {**admin, "X-Cost-Center-Id": str(north["cost_center_id"])}
    bus = client.post("/api/vehicles", headers=in_north, json={"fleet_number": "N1", "registration_number": "R-N1"}).json()
    s = client.post("/api/schedules", headers=in_north, json={"schedule_code": "N-S1", "schedule_name": "x",
                                                              "vehicle_id": bus["vehicle_id"], "effective_from": "2026-11-01"}).json()
    vid = s["versions"][0]["schedule_version_id"]
    r = add({**world, "h": in_north}, vid, trip_body(world, "up", "T1", "06:00", "06:20", "06:22", "06:50"))
    assert r.status_code == 422                                          # default cost center's route and locations
