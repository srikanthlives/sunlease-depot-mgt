from .conftest import login


def test_login_and_roles(client):
    assert client.post("/api/auth/login", json={"username": "admin", "password": "bad"}).status_code == 401
    viewer = login(client, "viewer", "Viewer@123")
    assert client.get("/api/vehicles", headers=viewer).status_code == 200
    r = client.post("/api/locations", json={"location_code": "X", "location_name": "X"}, headers=viewer)
    assert r.status_code == 403
    assert client.get("/api/vehicles").status_code == 401


def test_route_directions_have_independent_stops_and_distances(world):
    up, down = world["up"], world["down"]
    assert float(up["total_distance_km"]) == 10 and float(down["total_distance_km"]) == 10.5
    assert [float(s["cumulative_distance_km"]) for s in up["stops"]] == [0, 4, 10]
    assert [float(s["cumulative_distance_km"]) for s in down["stops"]] == [0, 6.5, 10.5]
    # reverse direction has its own stop records
    assert {s["route_stop_id"] for s in up["stops"]}.isdisjoint({s["route_stop_id"] for s in down["stops"]})


def test_stops_must_match_terminals(world):
    loc, c = world["loc"], world["client"]
    r = c.post(f"/api/directions/{world['up']['direction_id']}/stops", headers=world["h"], json={"stops": [
        {"location_id": loc["MID"]}, {"location_id": loc["TB"], "distance_from_previous_km": 5}]})
    assert r.status_code == 422 and "start terminal" in r.text
    r = c.post(f"/api/directions/{world['up']['direction_id']}/stops", headers=world["h"], json={"stops": [
        {"location_id": loc["TA"]}, {"location_id": loc["MID"], "distance_from_previous_km": 5}]})
    assert r.status_code == 422 and "end terminal" in r.text


def test_duplicate_codes_rejected(world):
    c = world["client"]
    r = c.post("/api/locations", json={"location_code": "DEP", "location_name": "dup"}, headers=world["h"])
    assert r.status_code == 409
    r = c.post("/api/vehicles", json={"fleet_number": "B1", "registration_number": "other"}, headers=world["h"])
    assert r.status_code == 409


def test_soc_and_battery_validation(world):
    c = world["client"]
    r = c.post("/api/vehicles", json={"fleet_number": "Z", "registration_number": "Z", "battery_capacity_kwh": -5},
               headers=world["h"])
    assert r.status_code == 422


def test_location_in_use_cannot_be_deleted(world):
    c = world["client"]
    r = c.delete(f"/api/locations/{world['loc']['TA']}", headers=world["h"])
    assert r.status_code == 409


def test_employee_stints_and_availability(client, admin):
    base = {"employee_number": "E1", "full_name": "A", "staff_type": "DRIVER"}
    r = client.post("/api/employees", json={**base, "start_date": "2025-01-01", "end_date": "2025-12-31"}, headers=admin)
    assert r.status_code == 201
    # overlapping stint rejected
    r = client.post("/api/employees", json={**base, "start_date": "2025-06-01"}, headers=admin)
    assert r.status_code == 409
    # rejoin after separation is a new row
    r = client.post("/api/employees", json={**base, "start_date": "2026-03-01"}, headers=admin)
    assert r.status_code == 201
    # end before start rejected
    r = client.post("/api/employees", json={**base, "employee_number": "E2", "start_date": "2025-05-01",
                                            "end_date": "2025-04-01"}, headers=admin)
    assert r.status_code == 422
    on = lambda d: {e["start_date"] for e in client.get(f"/api/employees?available_on={d}", headers=admin).json()}
    assert on("2025-12-31") == {"2025-01-01"}          # inclusive end date
    assert on("2026-01-15") == set()                   # gap between stints
    assert on("2026-03-01") == {"2026-03-01"}


def test_employee_excel_import(client, admin):
    import io
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Employee Number", "Full Name", "Designation", "Staff Type", "Home Depot Code", "Start Date", "End Date", "Status"])
    ws.append(["X1", "One", "Driver", "DRIVER", "", "01-Apr-2025", "", "ACTIVE"])
    ws.append(["X2", "Two", "Conductor", "CONDUCTOR", "", "2025-05-01", "30-Jun-2026", "ACTIVE"])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post("/api/employees-import", headers=admin, files={"file": ("e.xlsx", buf.getvalue())})
    assert r.json() == {"created": 2, "updated": 0, "errors": []}
    r = client.post("/api/employees-import", headers=admin, files={"file": ("e.xlsx", buf.getvalue())})
    assert r.json()["updated"] == 2
    # a bad row blocks the whole file
    ws.append(["X3", "Three", "Driver", "PILOT", "", "01-Apr-2025", "", "ACTIVE"])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post("/api/employees-import", headers=admin, files={"file": ("e.xlsx", buf.getvalue())}).json()
    assert r["created"] == 0 and r["errors"][0]["row"] == 4


def test_unused_bus_and_route_can_be_deleted(world):
    from .conftest import make_schedule
    c, h = world["client"], world["h"]
    s, _ = make_schedule(world)                     # uses bus B1, no trips yet
    buses = {v["fleet_number"]: v for v in c.get("/api/vehicles", headers=h).json()}
    assert buses["B1"]["in_use"] and not buses["B2"]["in_use"]
    assert c.delete(f"/api/vehicles/{world['bus']['vehicle_id']}", headers=h).status_code == 409
    assert c.delete(f"/api/vehicles/{world['bus2']['vehicle_id']}", headers=h).status_code == 204
    rid = world["route"]["route_id"]
    assert c.get(f"/api/routes/{rid}", headers=h).json()["in_use"] is False
    assert c.delete(f"/api/routes/{rid}", headers=h).status_code == 204
    assert c.get(f"/api/routes/{rid}", headers=h).status_code == 404
    # its terminals are free again
    assert c.delete(f"/api/locations/{world['loc']['MID']}", headers=h).status_code == 204


def test_route_with_trips_cannot_be_deleted(world):
    from .conftest import add, make_schedule, trip_body
    c, h = world["client"], world["h"]
    s, vid = make_schedule(world)
    assert add(world, vid, trip_body(world, "up", "T1", "06:00", "06:20", "06:22", "06:50")).status_code == 201
    r = c.delete(f"/api/routes/{world['route']['route_id']}", headers=h)
    assert r.status_code == 409 and "S1" in r.json()["detail"]
