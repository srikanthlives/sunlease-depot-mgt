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


# ---- HRMS sync: preview, then pull only what was ticked ----------------------
HRMS_PAYLOAD = [
    {"employee_number": "H1", "full_name": "Hrms One", "staff_type": "DRIVER", "start_date": "01-Apr-2025"},
    {"employee_number": "H2", "full_name": "Hrms Two", "staff_type": "CONDUCTOR", "start_date": "2025-05-01",
     "end_date": "2026-06-30"},
    {"employee_number": "H3", "full_name": "Hrms Bad", "staff_type": "PILOT", "start_date": "2025-05-01"},
]


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


def _fake_hrms(monkeypatch, payload=None):
    calls = []

    def get(url, headers=None, timeout=None):
        calls.append({"url": url, "headers": headers or {}})
        return _Resp(HRMS_PAYLOAD if payload is None else payload)

    monkeypatch.setattr("app.services.employee_service.requests.get", get)
    return calls


def test_hrms_sync_is_configured_in_settings_and_token_never_leaves_the_server(client, admin):
    assert client.get("/api/employees-hrms-preview", headers=admin).status_code == 400  # not configured
    r = client.put("/api/settings", headers=admin,
                   json={"values": {"hrms_sync_url": "not-a-url", "hrms_sync_token": "t"}})
    assert r.status_code == 422 and "http" in r.text
    r = client.put("/api/settings", headers=admin,
                   json={"values": {"hrms_sync_url": "https://hrms.example/api/employees",
                                    "hrms_sync_token": "secret-token"}})
    assert r.status_code == 200
    shown = client.get("/api/settings", headers=admin).json()["values"]
    assert shown["hrms_sync_url"] == "https://hrms.example/api/employees"
    assert shown["hrms_sync_token"] == "********"          # the secret is masked, not sent
    # saving the form back with the mask keeps the stored token
    client.put("/api/settings", headers=admin, json={"values": {"hrms_sync_token": "********"}})
    from app.services import employee_service
    cc = int(client.get("/api/settings", headers=admin).json()["cost_center_id"])
    from app.db.session import SessionLocal
    with SessionLocal() as s:
        assert employee_service.hrms_config(s, cc)[1] == "secret-token"


def test_hrms_preview_marks_each_row_and_sync_pulls_only_the_selection(client, admin, monkeypatch):
    client.put("/api/settings", headers=admin,
               json={"values": {"hrms_sync_url": "https://hrms.example/api/employees",
                                "hrms_sync_token": "secret-token"}})
    calls = _fake_hrms(monkeypatch)
    rows = client.get("/api/employees-hrms-preview", headers=admin).json()["employees"]
    assert calls[0]["headers"]["Authorization"] == "Bearer secret-token"
    by_num = {r["employee_number"]: r for r in rows}
    assert by_num["H1"]["action"] == "NEW" and by_num["H2"]["action"] == "NEW"
    assert by_num["H3"]["action"] == "BLOCKED" and by_num["H3"]["key"] is None   # bad staff type
    assert not client.get("/api/employees", headers=admin).json()               # preview wrote nothing

    # pull H1 only
    r = client.post("/api/employees-sync-hrms", headers=admin, json={"keys": [by_num["H1"]["key"]]}).json()
    assert (r["created"], r["updated"], r["errors"]) == (1, 0, [])
    assert [e["employee_number"] for e in client.get("/api/employees", headers=admin).json()] == ["H1"]

    # H1 now shows as an update; pulling it again updates rather than duplicates
    again = {r["employee_number"]: r for r in
             client.get("/api/employees-hrms-preview", headers=admin).json()["employees"]}
    assert again["H1"]["action"] == "UPDATE"
    r = client.post("/api/employees-sync-hrms", headers=admin, json={"keys": [again["H1"]["key"]]}).json()
    assert (r["created"], r["updated"]) == (0, 1)
    assert len(client.get("/api/employees", headers=admin).json()) == 1


def test_hrms_sync_rejects_an_empty_selection_and_reports_a_vanished_row(client, admin, monkeypatch):
    client.put("/api/settings", headers=admin,
               json={"values": {"hrms_sync_url": "https://hrms.example/api/employees"}})
    _fake_hrms(monkeypatch)
    assert client.post("/api/employees-sync-hrms", headers=admin, json={"keys": []}).status_code == 422
    r = client.post("/api/employees-sync-hrms", headers=admin, json={"keys": ["H9|2025-01-01"]}).json()
    assert r["created"] == 0 and "no longer in the HRMS payload" in r["errors"][0]["error"]
    # no body still pulls everything selectable, as before
    r = client.post("/api/employees-sync-hrms", headers=admin).json()
    assert r["created"] == 2 and len(r["errors"]) == 1       # H3 has a bad staff type
