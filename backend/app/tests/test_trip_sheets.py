"""Trip sheets: entry, billing (planned km minus lost km), driver changes, workflow and locks."""
import pytest

from .conftest import login, make_schedule
from .test_schedules import build_good

DATE = "2026-11-05"


def published(world):
    s, vid = make_schedule(world)
    build_good(world, vid)
    assert world["client"].post(f"/api/schedule-versions/{vid}/publish", json={}, headers=world["h"]).status_code == 200
    return s, vid


def staff(world, number, staff_type="DRIVER"):
    return world["post"]("/api/employees", {"employee_number": number, "full_name": f"Staff {number}",
                                            "staff_type": staff_type, "start_date": "2025-01-01"})["employee_id"]


def new_sheet(world, s, date=DATE, h=None):
    r = world["client"].post("/api/trip-sheets", json={"schedule_id": s["schedule_id"], "operating_date": date},
                             headers=h or world["h"])
    assert r.status_code == 201, r.text
    return r.json()


def as_planned(sheet, odo=1000.0, **overrides):
    """Rows filled exactly as planned, with a continuous odometer; overrides[trip_number] patches a row."""
    rows = []
    for r in sheet["rows"]:
        p = r["planned"]
        row = {"row_id": r["row_id"], "status": "OPERATED",
               "actual_start_day_offset": p["start_day_offset"], "actual_start_time": p["start_time"],
               "actual_end_day_offset": p["end_day_offset"], "actual_end_time": p["end_time"]}
        if p["activity_type"] in ("PASSENGER_TRIP", "NON_REVENUE_MOVEMENT"):
            row.update(start_odometer_km=odo, end_odometer_km=odo + p["planned_km"])
            odo += p["planned_km"]
        row.update(overrides.get(p.get("trip_number"), {}))
        rows.append(row)
    return rows


def save(world, sheet, rows, crew=None, h=None):
    return world["client"].put(f"/api/trip-sheets/{sheet['sheet_id']}", headers=h or world["h"],
                               json={"paper_sheet_no": "P-1", "rows": rows, "crew": crew or []})


def driver_on(sheet, employee_id):
    c = next(c for c in sheet["crew"] if c["crew_role"] == "DRIVER")
    return [{**{k: c[k] for k in ("crew_id", "duty_start_day_offset", "duty_start_time", "duty_end_day_offset",
                                   "duty_end_time")}, "employee_id": employee_id}]


def reason(world, code):
    return next(r["reason_id"] for r in world["client"].get("/api/trip-reasons", headers=world["h"]).json()
                if r["reason_code"] == code)


def test_sheet_is_laid_out_from_the_published_version(world):
    s, vid = published(world)
    sheet = new_sheet(world, s)
    assert sheet["schedule_version_id"] == vid and len(sheet["rows"]) == 5
    assert all(r["status"] == "PENDING" for r in sheet["rows"])
    assert [c["crew_role"] for c in sheet["crew"]] == ["DRIVER"]                     # single-driver default
    assert sheet["crew"][0]["duty_start_time"] == "05:00" and sheet["crew"][0]["duty_end_time"] == "08:45"
    # one sheet per schedule per date, and only where a published version applies
    c = world["client"]
    assert c.post("/api/trip-sheets", json={"schedule_id": s["schedule_id"], "operating_date": DATE}, headers=world["h"]).status_code == 409
    assert c.post("/api/trip-sheets", json={"schedule_id": s["schedule_id"], "operating_date": "2026-10-01"}, headers=world["h"]).status_code == 422
    board = c.get(f"/api/trip-sheets/board?date={DATE}", headers=world["h"]).json()
    assert board[0]["status"] == "DRAFT" and board[0]["sheet_id"] == sheet["sheet_id"]


def test_operated_as_planned_bills_planned_km_and_goes_through_workflow(world):
    s, _ = published(world)
    sheet = new_sheet(world, s)
    c, h = world["client"], world["h"]
    # pending rows and a missing driver block submission
    r = c.post(f"/api/trip-sheets/{sheet['sheet_id']}/submit", headers=h)
    assert r.status_code == 422 and {"ROW_PENDING", "CREW_MISSING"} <= {i["code"] for i in r.json()["detail"]["issues"]}
    d = staff(world, "D1")
    r = save(world, sheet, as_planned(sheet), driver_on(sheet, d))
    assert r.status_code == 200, r.text
    summ = r.json()["summary"]
    assert summ["billable_km"] == 20.5 and summ["deducted_km"] == 0                 # movements are non-payable
    assert summ["odometer_km"] == 30.5 and summ["trips_operated"] == 2
    assert c.post(f"/api/trip-sheets/{sheet['sheet_id']}/submit", headers=h).status_code == 200
    assert save(world, sheet, as_planned(sheet)).status_code == 409                   # submitted = not editable
    assert c.post(f"/api/trip-sheets/{sheet['sheet_id']}/approve", headers=h).json()["status"] == "APPROVED"


def test_partial_trip_bills_km_up_to_the_stop_and_attribution_decides_the_rest(world):
    s, _ = published(world)
    sheet = new_sheet(world, s)
    down = next(r for r in sheet["rows"] if r["planned"].get("trip_number") == "T2")["planned"]
    mid = next(st for st in down["stops"] if st["location_code"] == "MID")             # 6.5 km into the 10.5 km trip
    cut = {"status": "PARTIAL", "stopped_at_route_stop_id": mid["route_stop_id"], "reason_id": reason(world, "BREAKDOWN"),
           "actual_end_time": "07:30", "end_odometer_km": 1021.5}
    r = save(world, sheet, as_planned(sheet, T2=cut))
    summ = r.json()["summary"]
    assert summ["trips_partial"] == 1 and summ["billable_km"] == 10 + 6.5 and summ["deducted_km"] == 4.0
    row = next(x for x in r.json()["rows"] if x["planned"].get("trip_number") == "T2")
    assert row["attributable_to"] == "OPERATOR"                                         # reason's default
    # the same loss attributable to the client is still billed (cost-center setting, default CLIENT)
    r = save(world, sheet, as_planned(sheet, T2={**cut, "attributable_to": "CLIENT"}))
    assert r.json()["summary"]["billable_km"] == 20.5 and r.json()["summary"]["lost_billed_km"] == 4.0


def test_cancelled_trip_is_deducted_unless_billed_attribution(world):
    s, _ = published(world)
    sheet = new_sheet(world, s)
    cancel = {"status": "CANCELLED", "reason_id": reason(world, "ROAD_CLOSED"), "start_odometer_km": None, "end_odometer_km": None}
    summ = save(world, sheet, as_planned(sheet, T1=cancel)).json()["summary"]
    assert summ["billable_km"] == 10.5 and summ["deducted_km"] == 10 and summ["trips_cancelled"] == 1
    # cost center decides to bill external causes too
    c, h = world["client"], world["h"]
    assert c.put("/api/settings", json={"values": {"bill_lost_km_attributable_to": ["CLIENT", "EXTERNAL"]}}, headers=h).status_code == 200
    assert c.get(f"/api/trip-sheets/{sheet['sheet_id']}", headers=h).json()["summary"]["billable_km"] == 20.5
    # cancelling needs a reason and an attribution
    v = c.post(f"/api/trip-sheets/{sheet['sheet_id']}/validate", headers=h).json()
    save(world, sheet, as_planned(sheet, T1={"status": "CANCELLED"}))
    codes = {i["code"] for i in c.post(f"/api/trip-sheets/{sheet['sheet_id']}/validate", headers=h).json()["issues"]}
    assert {"REASON_MISSING", "ATTRIBUTION_MISSING"} <= codes and v["valid"] is False   # (crew still missing)


def test_odometer_checks(world):
    s, _ = published(world)
    sheet = new_sheet(world, s)
    c, h = world["client"], world["h"]
    rows = as_planned(sheet, T2={"start_odometer_km": 1005.0, "end_odometer_km": 1030.0})   # restarts below T1's end, 25 km for 10.5
    save(world, sheet, rows)
    codes = {i["code"] for i in c.post(f"/api/trip-sheets/{sheet['sheet_id']}/validate", headers=h).json()["issues"]}
    assert {"ODO_CONTINUITY", "ODO_DEVIATION"} <= codes


def test_driver_change_cuts_the_first_drivers_working_time(world):
    s, _ = published(world)
    sheet = new_sheet(world, s)
    c, h = world["client"], world["h"]
    a, b = staff(world, "D1"), staff(world, "D2")
    sheet = save(world, sheet, as_planned(sheet), driver_on(sheet, a)).json()
    crew_id = sheet["crew"][0]["crew_id"]
    r = c.post(f"/api/trip-sheet-crew/{crew_id}/handover", headers=h,
               json={"at_time": "07:00", "employee_id": b, "reason": "Driver unwell"})
    assert r.status_code == 200, r.text
    crew = {x["employee_id"]: x for x in r.json()["crew"]}
    assert crew[a]["duty_end_time"] == "07:00" and crew[a]["working_minutes"] == 120
    assert crew[b]["duty_start_time"] == "07:00" and crew[b]["working_minutes"] == 105 and crew[b]["replaces_crew_id"] == crew_id
    v = c.post(f"/api/trip-sheets/{sheet['sheet_id']}/validate", headers=h).json()
    assert v["valid"], v["issues"]
    # the change time must fall inside the duty
    assert c.post(f"/api/trip-sheet-crew/{crew_id}/handover", headers=h,
                  json={"at_time": "09:30", "employee_id": a, "reason": "x"}).status_code == 422


def test_crew_checks(world):
    s, _ = published(world)
    s2, vid2 = make_schedule(world, code="S2", bus_key="bus2")
    build_good(world, vid2)
    c, h = world["client"], world["h"]
    assert c.post(f"/api/schedule-versions/{vid2}/publish", json={}, headers=h).status_code == 200
    cond, d = staff(world, "C1", "CONDUCTOR"), staff(world, "D1")
    sheet = new_sheet(world, s)
    save(world, sheet, as_planned(sheet), driver_on(sheet, cond))
    codes = {i["code"] for i in c.post(f"/api/trip-sheets/{sheet['sheet_id']}/validate", headers=h).json()["issues"]}
    assert "CREW_TYPE" in codes
    # the same driver on two buses at the same time
    save(world, sheet, as_planned(sheet), driver_on(sheet, d))
    other = new_sheet(world, s2)
    save(world, other, as_planned(other), driver_on(other, d))
    codes = {i["code"] for i in c.post(f"/api/trip-sheets/{other['sheet_id']}/validate", headers=h).json()["issues"]}
    assert "CREW_DOUBLE_BOOKED" in codes


def test_shift_based_crew_from_the_version(world):
    c, h = world["client"], world["h"]
    s, vid = make_schedule(world)
    build_good(world, vid)
    crew = {"crew_mode": "SHIFTS", "conductor_required": True, "shifts": [
        {"shift_name": "A", "start_time": "05:00", "end_time": "07:00"},
        {"shift_name": "B", "start_time": "06:30", "end_time": "09:00"}]}
    assert c.put(f"/api/schedule-versions/{vid}/crew", json=crew, headers=h).status_code == 200
    res = c.post(f"/api/schedule-versions/{vid}/validate", headers=h).json()
    assert "SHIFT_OVERLAP" in {i["code"] for i in res["issues"] if i["severity"] == "ERROR"}
    crew["shifts"][1]["start_time"] = "07:00"
    v = c.put(f"/api/schedule-versions/{vid}/crew", json=crew, headers=h).json()
    assert [x["shift_name"] for x in v["shifts"]] == ["A", "B"]
    assert c.post(f"/api/schedule-versions/{vid}/publish", json={}, headers=h).status_code == 200
    assert c.put(f"/api/schedule-versions/{vid}/crew", json=crew, headers=h).status_code == 409   # locked with the version
    sheet = new_sheet(world, s)
    assert sorted((x["shift_name"], x["crew_role"]) for x in sheet["crew"]) == [
        ("A", "CONDUCTOR"), ("A", "DRIVER"), ("B", "CONDUCTOR"), ("B", "DRIVER")]
    # a new version copies the crew pattern
    v2 = c.post(f"/api/schedules/{s['schedule_id']}/versions", json={"valid_from": "2026-12-01"}, headers=h).json()
    assert v2["crew_mode"] == "SHIFTS" and len(v2["shifts"]) == 2


def test_versions_used_by_trip_sheets_are_protected(world):
    s, vid = published(world)
    new_sheet(world, s)
    c, h = world["client"], world["h"]
    assert c.post(f"/api/schedule-versions/{vid}/unpublish", headers=h).status_code == 409
    v2 = c.post(f"/api/schedules/{s['schedule_id']}/versions", json={"valid_from": "2026-11-03"}, headers=h).json()
    r = c.post(f"/api/schedule-versions/{v2['schedule_version_id']}/publish", json={"acknowledge_warnings": True}, headers=h)
    assert r.status_code == 409 and DATE in r.text
    assert c.put(f"/api/schedules/{s['schedule_id']}", json={"effective_to": "2026-11-04"}, headers=h).status_code == 409
    # future-dated versions show as SCHEDULED until they start
    import datetime as dt
    versions = {v["version_number"]: v["effective_status"] for v in c.get(f"/api/schedules/{s['schedule_id']}", headers=h).json()["versions"]}
    assert versions[2] == "DRAFT"
    assert versions[1] == ("SCHEDULED" if dt.date.today() < dt.date(2026, 11, 1) else "LIVE")


def test_approved_sheet_is_locked_and_only_admin_reopens(world, db):
    s, _ = published(world)
    sheet = new_sheet(world, s)
    c, h = world["client"], world["h"]
    save(world, sheet, as_planned(sheet), driver_on(sheet, staff(world, "D1")))
    c.post(f"/api/trip-sheets/{sheet['sheet_id']}/submit", headers=h)
    c.post(f"/api/trip-sheets/{sheet['sheet_id']}/approve", headers=h)
    from sqlalchemy import text
    from sqlalchemy.exc import DatabaseError
    with pytest.raises(DatabaseError):
        db.execute(text(f"UPDATE trip_sheet_rows SET status='CANCELLED' WHERE sheet_id={sheet['sheet_id']}"))
        db.commit()
    db.rollback()
    pub = login(c, "publisher", "Publisher@123")
    assert c.post(f"/api/trip-sheets/{sheet['sheet_id']}/return", json={"reason": "fix km"}, headers=pub).status_code == 403
    r = c.post(f"/api/trip-sheets/{sheet['sheet_id']}/return", json={"reason": "fix km"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "DRAFT"


def test_mis_clerk_enters_and_submits_but_cannot_approve_or_edit_schedules(world):
    s, vid = published(world)
    c, h = world["client"], world["h"]
    cc = int(h["X-Cost-Center-Id"])
    assert c.post("/api/users", json={"username": "clerk", "password": "Clerk@123",
                                      "cost_center_roles": [{"cost_center_id": cc, "role": "MIS"}]}, headers=h).status_code == 201
    clerk = login(c, "clerk", "Clerk@123")
    d = staff(world, "D1")
    sheet = new_sheet(world, s, h=clerk)
    assert save(world, sheet, as_planned(sheet), driver_on(sheet, d), h=clerk).status_code == 200
    assert c.post(f"/api/trip-sheets/{sheet['sheet_id']}/submit", headers=clerk).status_code == 200
    assert c.post(f"/api/trip-sheets/{sheet['sheet_id']}/approve", headers=clerk).status_code == 403
    assert c.post("/api/vehicles", json={"fleet_number": "Z", "registration_number": "Z"}, headers=clerk).status_code == 403
    v2 = c.post(f"/api/schedules/{s['schedule_id']}/versions", json={"valid_from": "2026-12-01"}, headers=clerk)
    assert v2.status_code == 403


def test_extra_unplanned_run(world):
    s, _ = published(world)
    sheet = new_sheet(world, s)
    c, h = world["client"], world["h"]
    after = sheet["rows"][1]["row_id"]
    sheet = c.post(f"/api/trip-sheets/{sheet['sheet_id']}/extra-rows?after_row_id={after}", headers=h).json()
    extra = sheet["rows"][2]
    assert extra["is_extra"] and len(sheet["rows"]) == 6
    rows = as_planned({**sheet, "rows": [r for r in sheet["rows"] if not r["is_extra"]]})
    rows.append({"row_id": extra["row_id"], "status": "OPERATED", "actual_start_time": "06:50", "actual_end_time": "07:05",
                 "start_odometer_km": 1015.0, "end_odometer_km": 1018.0, "extra_payable": True,
                 "extra_from_location_id": world["loc"]["TB"], "extra_to_location_id": world["loc"]["CHG"]})
    assert save(world, sheet, rows).json()["summary"]["billable_km"] == 20.5 + 3
    assert c.delete(f"/api/trip-sheet-rows/{sheet['rows'][0]['row_id']}", headers=h).status_code == 409   # planned row
    assert c.delete(f"/api/trip-sheet-rows/{extra['row_id']}", headers=h).status_code == 200


def test_opening_odometer_follows_previous_closing(world):
    s, _ = published(world)
    c, h = world["client"], world["h"]
    day1 = new_sheet(world, s, "2026-11-05")
    save(world, day1, as_planned(day1, odo=1000.0))                      # closes at 1030.5
    day2 = new_sheet(world, s, "2026-11-06")
    assert float(day2["previous_closing"]["odometer_km"]) == 1030.5
    save(world, day2, as_planned(day2, odo=1040.0))                      # 9.5 km unaccounted overnight
    codes = {(i["code"], i["severity"]) for i in c.post(f"/api/trip-sheets/{day2['sheet_id']}/validate", headers=h).json()["issues"]}
    assert ("ODO_OVERNIGHT", "WARNING") in codes
    save(world, day2, as_planned(day2, odo=1020.0))                      # below the closing reading
    codes = {(i["code"], i["severity"]) for i in c.post(f"/api/trip-sheets/{day2['sheet_id']}/validate", headers=h).json()["issues"]}
    assert ("ODO_OVERNIGHT", "ERROR") in codes
    save(world, day2, as_planned(day2, odo=1030.5))
    codes = {i["code"] for i in c.post(f"/api/trip-sheets/{day2['sheet_id']}/validate", headers=h).json()["issues"]}
    assert "ODO_OVERNIGHT" not in codes


def test_paper_version_warning(world):
    s, _ = published(world)
    sheet = new_sheet(world, s)
    c, h = world["client"], world["h"]
    save_body = {"rows": as_planned(sheet), "crew": driver_on(sheet, staff(world, "D1")), "paper_version_number": 2}
    assert c.put(f"/api/trip-sheets/{sheet['sheet_id']}", json=save_body, headers=h).status_code == 200
    issues = c.post(f"/api/trip-sheets/{sheet['sheet_id']}/validate", headers=h).json()["issues"]
    assert ("PAPER_VERSION", "WARNING") in {(i["code"], i["severity"]) for i in issues}
    save_body["paper_version_number"] = 1
    c.put(f"/api/trip-sheets/{sheet['sheet_id']}", json=save_body, headers=h)
    assert "PAPER_VERSION" not in {i["code"] for i in c.post(f"/api/trip-sheets/{sheet['sheet_id']}/validate", headers=h).json()["issues"]}


def test_bus_change_restarts_odometer_and_keeps_next_day_opening_on_own_bus(world):
    s, _ = published(world)
    c, h = world["client"], world["h"]
    d = staff(world, "D1")
    day1 = new_sheet(world, s, "2026-11-05")
    t2 = next(r for r in day1["rows"] if r["planned"].get("trip_number") == "T2")
    # bus B2 takes over from T2: its odometer reads 5000+, which is fine after the change
    rows = as_planned(day1, odo=1000.0)
    after = False
    for r in rows:
        if r["row_id"] == t2["row_id"]:
            after = True
        if after and "start_odometer_km" in r:
            r["start_odometer_km"] += 4000; r["end_odometer_km"] += 4000
    body = {"rows": rows, "crew": driver_on(day1, d), "bus_change_registration": "r-b2", "bus_change_from_row_id": t2["row_id"],
            "bus_change_reason_id": reason(world, "BREAKDOWN")}
    r = c.put(f"/api/trip-sheets/{day1['sheet_id']}", json=body, headers=h)
    assert r.status_code == 200 and r.json()["bus_change_vehicle_id"] == world["bus2"]["vehicle_id"]   # matched ignoring case/dashes
    v = c.post(f"/api/trip-sheets/{day1['sheet_id']}/validate", headers=h).json()
    assert v["valid"], v["issues"]
    # next day: the assigned bus opens from its own last reading (before the change), not the other bus's
    day2 = new_sheet(world, s, "2026-11-06")
    assert float(day2["previous_closing"]["odometer_km"]) == 1015.0          # end of T1 on the assigned bus
    # billing shows both buses for that day
    c.post(f"/api/trip-sheets/{day1['sheet_id']}/submit", headers=h); c.post(f"/api/trip-sheets/{day1['sheet_id']}/approve", headers=h)
    rep = c.get("/api/reports/billing?date_from=2026-11-01&date_to=2026-11-30", headers=h).json()
    assert rep["daily"][0]["fleet_number"] == "B1 → B2"


def test_bus_change_checks(world):
    s, _ = published(world)
    sheet = new_sheet(world, s)
    c, h = world["client"], world["h"]
    body = {"rows": as_planned(sheet), "crew": driver_on(sheet, staff(world, "D1")), "bus_change_registration": "ZZ99XX0001"}
    c.put(f"/api/trip-sheets/{sheet['sheet_id']}", json=body, headers=h)
    codes = {(i["code"], i["severity"]) for i in c.post(f"/api/trip-sheets/{sheet['sheet_id']}/validate", headers=h).json()["issues"]}
    assert {("BUS_CHANGE_UNKNOWN", "WARNING"), ("BUS_CHANGE_RUN", "ERROR"), ("BUS_CHANGE_REASON", "ERROR")} <= codes
    body["bus_change_registration"] = "R-B1"                                # the assigned bus itself
    c.put(f"/api/trip-sheets/{sheet['sheet_id']}", json=body, headers=h)
    codes = {i["code"] for i in c.post(f"/api/trip-sheets/{sheet['sheet_id']}/validate", headers=h).json()["issues"]}
    assert "BUS_CHANGE_SAME" in codes
