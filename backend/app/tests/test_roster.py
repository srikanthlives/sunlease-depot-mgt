"""Duty roster, step 1: the availability register and the lock triggers behind it."""
import datetime as dt

import pytest
from sqlalchemy import text

from app.models.models import BusSchedule, DutyActual, DutyAssignment, DutyRoster, DutyRosterVersion
from app.tests.conftest import login, make_schedule


def _emp(client, admin, number, name, staff_type="DRIVER", start="2025-01-01", end=None):
    body = {"employee_number": number, "full_name": name, "staff_type": staff_type, "start_date": start}
    if end:
        body["end_date"] = end
    r = client.post("/api/employees", json=body, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()["employee_id"]


def test_availability_crud_and_overlap(client, admin):
    e1 = _emp(client, admin, "E1", "Driver One")
    e2 = _emp(client, admin, "E2", "Driver Two")

    r = client.post("/api/employee-availability", headers=admin, json={
        "employee_id": e1, "status": "LEAVE", "from_date": "2026-10-05", "to_date": "2026-10-09",
        "remarks": "annual leave"})
    assert r.status_code == 201, r.text
    first = r.json()
    assert first["employee_number"] == "E1" and first["staff_type"] == "DRIVER"

    # the same employee cannot be marked twice over the same day
    r = client.post("/api/employee-availability", headers=admin, json={
        "employee_id": e1, "status": "SICK", "from_date": "2026-10-09", "to_date": "2026-10-12"})
    assert r.status_code == 409 and "overlaps" in r.json()["detail"].lower()

    # abutting ranges are fine, and so is the same window for somebody else
    for body in ({"employee_id": e1, "status": "SICK", "from_date": "2026-10-10", "to_date": "2026-10-12"},
                 {"employee_id": e2, "status": "WEEKLY_OFF", "from_date": "2026-10-05", "to_date": "2026-10-05"}):
        assert client.post("/api/employee-availability", headers=admin, json=body).status_code == 201

    # a window query returns entries that merely touch it, not only those inside it
    inside = client.get("/api/employee-availability?date_from=2026-10-08&date_to=2026-10-08", headers=admin).json()
    assert {x["employee_id"] for x in inside} == {e1}
    assert len(client.get("/api/employee-availability?date_from=2026-10-01&date_to=2026-10-31",
                          headers=admin).json()) == 3

    r = client.put(f"/api/employee-availability/{first['availability_id']}", headers=admin, json={
        "employee_id": e1, "status": "TRAINING", "from_date": "2026-10-05", "to_date": "2026-10-06"})
    assert r.status_code == 200 and r.json()["status"] == "TRAINING"

    assert client.delete(f"/api/employee-availability/{first['availability_id']}", headers=admin).status_code == 204
    assert len(client.get("/api/employee-availability", headers=admin).json()) == 2


def test_availability_rejects_bad_input(client, admin):
    e1 = _emp(client, admin, "E1", "Driver One")
    r = client.post("/api/employee-availability", headers=admin, json={
        "employee_id": e1, "status": "HOLIDAY", "from_date": "2026-10-05", "to_date": "2026-10-09"})
    assert r.status_code == 422
    r = client.post("/api/employee-availability", headers=admin, json={
        "employee_id": e1, "status": "LEAVE", "from_date": "2026-10-09", "to_date": "2026-10-05"})
    assert r.status_code == 422
    r = client.post("/api/employee-availability", headers=admin, json={
        "employee_id": 9999, "status": "LEAVE", "from_date": "2026-10-05", "to_date": "2026-10-09"})
    assert r.status_code == 422


def test_free_on_combines_stint_dates_and_register(client, admin):
    on_rolls = _emp(client, admin, "E1", "Driver One")
    _emp(client, admin, "E2", "Driver Two", start="2026-11-01")              # joins later
    left = _emp(client, admin, "E3", "Driver Three", end="2026-09-30")       # already left
    conductor = _emp(client, admin, "C1", "Conductor One", staff_type="CONDUCTOR")
    client.post("/api/employee-availability", headers=admin, json={
        "employee_id": conductor, "status": "LEAVE", "from_date": "2026-10-20", "to_date": "2026-10-26"})

    r = client.get("/api/employees-free-on?on=2026-10-25", headers=admin)
    assert r.status_code == 200, r.text
    body = r.json()
    free = {x["employee_id"] for x in body["free"]}
    unavailable = {x["employee_id"]: x["reason"] for x in body["unavailable"]}

    assert on_rolls in free
    assert conductor in unavailable and "leave" in unavailable[conductor].lower()
    # somebody off the rolls is neither free nor listed as unavailable: they are not staff that day
    assert left not in free and left not in unavailable

    drivers = client.get("/api/employees-free-on?on=2026-10-25&staff_type=DRIVER", headers=admin).json()
    assert conductor not in {x["employee_id"] for x in drivers["free"] + drivers["unavailable"]}


def _roster(db, code: str) -> DutyRoster:
    """A roster on the cost center and schedule the `world` fixture created."""
    schedule = db.query(BusSchedule).first()
    roster = DutyRoster(cost_center_id=schedule.cost_center_id, roster_code=code,
                        period_from=dt.date(2026, 10, 1), period_to=dt.date(2026, 10, 31))
    db.add(roster)
    db.flush()
    return roster, schedule.schedule_id


def test_published_assignments_are_immutable(db, world):
    """The DB rejects a change to a published version's assignment even when the API is bypassed."""
    make_schedule(world)
    roster, schedule_id = _roster(db, "OCT26")
    v = DutyRosterVersion(roster_id=roster.roster_id, version_number=1, status="DRAFT")
    db.add(v)
    db.flush()
    a = DutyAssignment(roster_version_id=v.roster_version_id, duty_date=dt.date(2026, 10, 20),
                       schedule_id=schedule_id, crew_role="DRIVER", source="MANUAL")
    db.add(a)
    db.commit()

    v.status = "PUBLISHED"
    db.commit()
    with pytest.raises(Exception, match="immutable"):
        db.execute(text("UPDATE duty_assignments SET remarks = 'x' WHERE assignment_id = :i"),
                   {"i": a.assignment_id})
    db.rollback()


def test_closed_days_are_locked(db, world):
    make_schedule(world)
    roster, schedule_id = _roster(db, "OCT26B")
    act = DutyActual(roster_id=roster.roster_id, duty_date=dt.date(2026, 10, 20), duty_type="SCHEDULE",
                     schedule_id=schedule_id, slot_index=0, segment=0, crew_role="DRIVER",
                     status="AS_PLANNED")
    db.add(act)
    db.commit()

    roster.locked_through = dt.date(2026, 10, 24)
    db.commit()
    with pytest.raises(Exception, match="closed"):
        db.execute(text("UPDATE duty_actuals SET status = 'REPLACED' WHERE actual_id = :i"),
                   {"i": act.actual_id})
    db.rollback()

    # a day after the lock is still open
    db.execute(text("INSERT INTO duty_actuals (roster_id, duty_date, duty_type, schedule_id, "
                    "slot_index, segment, crew_role, status) "
                    "VALUES (:r, '2026-10-26', 'SCHEDULE', :s, 0, 0, 'DRIVER', 'AS_PLANNED')"),
               {"r": roster.roster_id, "s": schedule_id})
    db.commit()


# --------------------------------------------------------------------------
# Step 2: the draft grid and its validation
# --------------------------------------------------------------------------
from .test_schedules import build_good        # noqa: E402

PERIOD = {"roster_code": "NOV26", "roster_name": "November 2026", "period_from": "2026-11-01",
          "period_to": "2026-11-07"}


def _published(world, code="S1", bus_key="bus", crew=None):
    """A schedule whose version is published, so the roster sees duty slots for its dates."""
    s, vid = make_schedule(world, code=code, bus_key=bus_key)
    build_good(world, vid)
    if crew:
        assert world["client"].put(f"/api/schedule-versions/{vid}/crew", json=crew,
                                   headers=world["h"]).status_code == 200
    assert world["client"].post(f"/api/schedule-versions/{vid}/publish", json={},
                                headers=world["h"]).status_code == 200
    return s, vid


def _staff(world, number, staff_type="DRIVER", **kw):
    body = {"employee_number": number, "full_name": f"Staff {number}", "staff_type": staff_type,
            "start_date": "2025-01-01", **kw}
    return world["post"]("/api/employees", body)["employee_id"]


def _roster_for(world):
    r = world["client"].post("/api/rosters", json=PERIOD, headers=world["h"])
    assert r.status_code == 201, r.text
    return r.json()


def _cells(client, h, roster_id, cells):
    return client.put(f"/api/rosters/{roster_id}/assignments", json={"cells": cells}, headers=h)


def test_grid_rows_come_from_the_schedule_version(world):
    """One row per duty slot: a shift-based schedule with a conductor needs four."""
    _published(world, crew={"crew_mode": "SHIFTS", "conductor_required": True, "shifts": [
        {"shift_name": "A", "start_time": "05:00", "end_time": "13:00"},
        {"shift_name": "B", "start_time": "13:00", "end_time": "21:00"}]})
    _published(world, code="S2", bus_key="bus2")          # SINGLE crew, driver only
    roster = _roster_for(world)

    g = world["client"].get(f"/api/rosters/{roster['roster_id']}/grid", headers=world["h"]).json()
    assert len(g["days"]) == 7
    assert [(r["schedule_code"], r["slot_label"]) for r in g["rows"]] == [
        ("S1", "Driver - A"), ("S1", "Driver - B"), ("S1", "Conductor - A"), ("S1", "Conductor - B"),
        ("S2", "Driver")]
    assert g["rows"][0]["duty_from"] == "05:00" and g["rows"][0]["duty_minutes"] == 480
    assert all(c["employee_id"] is None for c in g["rows"][0]["cells"].values())


def test_assignments_save_and_unfilled_slots_block_publishing(world):
    _published(world)
    roster = _roster_for(world)
    rid = roster["roster_id"]
    c, h = world["client"], world["h"]
    d1 = _staff(world, "D1")

    res = c.post(f"/api/rosters/{rid}/validate", headers=h).json()
    assert res["can_publish"] is False
    assert {i["code"] for i in res["issues"]} == {"UNFILLED"} and res["errors"] == 7   # one per day

    r = _cells(c, h, rid, [{"duty_date": f"2026-11-0{d}", "schedule_id": 1, "crew_role": "DRIVER",
                            "employee_id": d1} for d in range(1, 8)])
    assert r.status_code == 200, r.text
    g = r.json()
    assert g["rows"][0]["cells"]["2026-11-03"]["employee_number"] == "D1"
    assert g["rows"][0]["cells"]["2026-11-03"]["source"] == "MANUAL"

    res = c.post(f"/api/rosters/{rid}/validate", headers=h).json()
    assert res["errors"] == 0 and res["can_publish"] is True

    # clearing a cell puts the gap back
    assert _cells(c, h, rid, [{"duty_date": "2026-11-03", "schedule_id": 1, "crew_role": "DRIVER",
                               "employee_id": None}]).status_code == 200
    res = c.post(f"/api/rosters/{rid}/validate", headers=h).json()
    assert [i["duty_date"] for i in res["issues"]] == ["2026-11-03"]


def test_validation_catches_the_crew_rules(world):
    """Staff type, stint dates and nobody in two places at once - the trip sheet's rules, forward."""
    _published(world)
    _published(world, code="S2", bus_key="bus2")
    roster = _roster_for(world)
    rid = roster["roster_id"]
    c, h = world["client"], world["h"]

    conductor = _staff(world, "C1", "CONDUCTOR")
    leaver = _staff(world, "D2", end_date="2026-11-04")
    d1 = _staff(world, "D1")

    day = [{"duty_date": "2026-11-02", "schedule_id": 1, "crew_role": "DRIVER", "employee_id": conductor}]
    assert _cells(c, h, rid, day).status_code == 200
    codes = {i["code"] for i in c.post(f"/api/rosters/{rid}/validate", headers=h).json()["issues"]}
    assert "CREW_TYPE" in codes

    # off the rolls on the day, and leaving inside the period
    assert _cells(c, h, rid, [{"duty_date": "2026-11-06", "schedule_id": 1, "crew_role": "DRIVER",
                               "employee_id": leaver}]).status_code == 200
    issues = c.post(f"/api/rosters/{rid}/validate", headers=h).json()["issues"]
    assert "CREW_DATES" in {i["code"] for i in issues if i["duty_date"] == "2026-11-06"}
    assert _cells(c, h, rid, [{"duty_date": "2026-11-03", "schedule_id": 1, "crew_role": "DRIVER",
                               "employee_id": leaver}]).status_code == 200
    issues = c.post(f"/api/rosters/{rid}/validate", headers=h).json()["issues"]
    assert "CREW_STINT_ENDS" in {i["code"] for i in issues if i["duty_date"] == "2026-11-03"}

    # the same driver on two buses whose days overlap
    assert _cells(c, h, rid, [{"duty_date": "2026-11-05", "schedule_id": 1, "crew_role": "DRIVER",
                               "employee_id": d1},
                              {"duty_date": "2026-11-05", "schedule_id": 2, "crew_role": "DRIVER",
                               "employee_id": d1}]).status_code == 200
    issues = c.post(f"/api/rosters/{rid}/validate", headers=h).json()["issues"]
    assert "CREW_DOUBLE_BOOKED" in {i["code"] for i in issues if i["duty_date"] == "2026-11-05"}


def test_availability_register_only_warns(world):
    """The depot can roster somebody on a marked day; it is a warning, not a refusal."""
    _published(world)
    roster = _roster_for(world)
    rid = roster["roster_id"]
    c, h = world["client"], world["h"]
    d1 = _staff(world, "D1")
    assert c.post("/api/employee-availability", headers=h, json={
        "employee_id": d1, "status": "WEEKLY_OFF", "from_date": "2026-11-03",
        "to_date": "2026-11-03"}).status_code == 201

    assert _cells(c, h, rid, [{"duty_date": f"2026-11-0{d}", "schedule_id": 1, "crew_role": "DRIVER",
                               "employee_id": d1} for d in range(1, 8)]).status_code == 200
    res = c.post(f"/api/rosters/{rid}/validate", headers=h).json()
    warn = [i for i in res["issues"] if i["code"] == "CREW_UNAVAILABLE"]
    assert len(warn) == 1 and warn[0]["duty_date"] == "2026-11-03" and "weekly off" in warn[0]["message"]
    assert res["errors"] == 0 and res["can_publish"] is True        # a warning never blocks


def test_copy_days_repeats_a_week(world):
    _published(world)
    roster = _roster_for(world)
    rid = roster["roster_id"]
    c, h = world["client"], world["h"]
    d1 = _staff(world, "D1")

    assert _cells(c, h, rid, [{"duty_date": "2026-11-01", "schedule_id": 1, "crew_role": "DRIVER",
                               "employee_id": d1}]).status_code == 200
    r = c.post(f"/api/rosters/{rid}/copy-days", headers=h,
               json={"source_from": "2026-11-01", "target_from": "2026-11-04", "day_count": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["copied"] == 1                       # only the one filled day had anything to copy
    cells = body["rows"][0]["cells"]
    assert cells["2026-11-04"]["employee_number"] == "D1"
    assert cells["2026-11-05"]["employee_id"] is None

    # days outside the period are skipped, not an error
    r = c.post(f"/api/rosters/{rid}/copy-days", headers=h,
               json={"source_from": "2026-11-01", "target_from": "2026-11-06", "day_count": 5}).json()
    assert r["skipped_days"] == 3


def test_roster_period_rules(world):
    _published(world)
    c, h = world["client"], world["h"]
    assert c.post("/api/rosters", json=PERIOD, headers=h).status_code == 201
    # a second roster cannot cover the same days
    r = c.post("/api/rosters", json={**PERIOD, "roster_code": "NOV26B", "period_from": "2026-11-05",
                                     "period_to": "2026-11-20"}, headers=h)
    assert r.status_code == 409 and "overlaps" in r.json()["detail"].lower()
    assert c.post("/api/rosters", json={**PERIOD, "roster_code": "NOV26C", "period_from": "2026-11-08",
                                        "period_to": "2026-11-20"}, headers=h).status_code == 201
    # a date outside the period has no slot to fill
    roster = c.get("/api/rosters", headers=h).json()[-1]
    r = _cells(c, h, roster["roster_id"], [{"duty_date": "2026-12-25", "schedule_id": 1,
                                            "crew_role": "DRIVER", "employee_id": None}])
    assert r.status_code == 422 and "outside the roster period" in r.text


def test_viewer_cannot_change_the_grid(world):
    _published(world)
    roster = _roster_for(world)
    c = world["client"]
    viewer = login(c, "viewer", "Viewer@123")
    assert c.get(f"/api/rosters/{roster['roster_id']}/grid", headers=viewer).status_code == 200
    r = _cells(c, viewer, roster["roster_id"], [{"duty_date": "2026-11-02", "schedule_id": 1,
                                                 "crew_role": "DRIVER", "employee_id": None}])
    assert r.status_code == 403


# --------------------------------------------------------------------------
# Crew and buses must belong to the same cost center
# --------------------------------------------------------------------------
def _two_cost_centers(client, admin):
    """A second company with two cost centers, both run by the super admin."""
    def post(url, body):
        r = client.post(url, json=body, headers=admin)
        assert r.status_code == 201, r.text
        return r.json()
    co = post("/api/companies", {"company_code": "ACME", "company_name": "Acme Transit"})
    north = post("/api/cost-centers", {"company_id": co["company_id"], "cost_center_code": "NORTH",
                                       "cost_center_name": "North depot"})
    south = post("/api/cost-centers", {"company_id": co["company_id"], "cost_center_code": "SOUTH",
                                       "cost_center_name": "South depot"})
    return co, north["cost_center_id"], south["cost_center_id"]


def _in_cc(admin, cc):
    return {**admin, "X-Cost-Center-Id": str(cc)}


def _sibling_cc(client, admin, code="DEPOT2"):
    """A second cost center in the SAME company as the default one, so an employee may move to it."""
    r = client.post("/api/cost-centers", headers=admin,
                    json={"company_id": 1, "cost_center_code": code, "cost_center_name": code})
    assert r.status_code == 201, r.text
    return r.json()["cost_center_id"]


def test_unused_employee_entered_in_the_wrong_depot_is_moved(client, admin):
    _, north, south = _two_cost_centers(client, admin)
    e = client.post("/api/employees", headers=_in_cc(admin, north), json={
        "employee_number": "D9", "full_name": "Driver Nine", "staff_type": "DRIVER",
        "start_date": "2025-01-01"}).json()

    r = client.post(f"/api/employees/{e['employee_id']}/transfer", headers=_in_cc(admin, north),
                    json={"cost_center_id": south})
    assert r.status_code == 200, r.text
    assert r.json()["cost_center_id"] == south and r.json()["employee_id"] == e["employee_id"]
    # and they are now only visible in the new depot
    assert [x["employee_number"] for x in client.get("/api/employees", headers=_in_cc(admin, south)).json()] == ["D9"]
    assert client.get("/api/employees", headers=_in_cc(admin, north)).json() == []


def test_a_used_employee_transfers_as_a_new_stint(world):
    """History stays with the depot where it happened, so the stint is split, not moved."""
    c, h = world["client"], world["h"]
    _published(world)
    roster = _roster_for(world)
    d1 = _staff(world, "D1")
    assert _cells(c, h, roster["roster_id"], [{"duty_date": "2026-11-02", "schedule_id": 1,
                                               "crew_role": "DRIVER", "employee_id": d1}]).status_code == 200
    other = _sibling_cc(c, h)

    usage = c.get(f"/api/employees/{d1}/usage", headers=h).json()
    assert usage["used"] == {"duty_assignments": 1}

    # without a date there is nothing to say when the old stint ended
    r = c.post(f"/api/employees/{d1}/transfer", headers=h, json={"cost_center_id": other})
    assert r.status_code == 422 and "needs a date" in r.json()["detail"]
    # nor can the new stint start before the old one did
    r = c.post(f"/api/employees/{d1}/transfer", headers=h,
               json={"cost_center_id": other, "effective_from": "2024-01-01"})
    assert r.status_code == 422 and "after the stint started" in r.json()["detail"]

    r = c.post(f"/api/employees/{d1}/transfer", headers=h,
               json={"cost_center_id": other, "effective_from": "2026-12-01"})
    assert r.status_code == 200, r.text
    moved = r.json()
    assert moved["employee_id"] != d1 and moved["cost_center_id"] == other
    assert moved["start_date"] == "2026-12-01"

    # the old stint stays where the duties happened, now ended the day before
    stints = {e["employee_id"]: e for e in c.get("/api/employees", headers=h).json()}
    assert stints[d1]["end_date"] == "2026-11-30"
    assert c.get(f"/api/rosters/{roster['roster_id']}/grid",
                 headers=h).json()["rows"][0]["cells"]["2026-11-02"]["employee_id"] == d1


def test_cross_company_transfer_is_refused(client, admin):
    _, north, _ = _two_cost_centers(client, admin)
    e = client.post("/api/employees", headers=admin, json={
        "employee_number": "D9", "full_name": "Driver Nine", "staff_type": "DRIVER",
        "start_date": "2025-01-01"}).json()
    r = client.post(f"/api/employees/{e['employee_id']}/transfer", headers=admin,
                    json={"cost_center_id": north, "effective_from": "2026-06-01"})
    assert r.status_code == 422 and "same company" in r.json()["detail"]


def test_crew_from_another_cost_center_is_refused_at_save(world):
    """Not merely flagged at validation: a cross-depot employee cannot be saved at all."""
    c, h = world["client"], world["h"]
    _published(world)
    roster = _roster_for(world)
    _, north, _ = _two_cost_centers(c, h)
    stranger = c.post("/api/employees", headers=_in_cc(h, north), json={
        "employee_number": "X1", "full_name": "Stranger One", "staff_type": "DRIVER",
        "start_date": "2025-01-01"}).json()["employee_id"]

    r = _cells(c, h, roster["roster_id"], [{"duty_date": "2026-11-02", "schedule_id": 1,
                                            "crew_role": "DRIVER", "employee_id": stranger}])
    assert r.status_code == 422 and "does not exist in this cost center" in r.text

    # the same rule on a trip sheet's crew
    sheet = c.post("/api/trip-sheets", json={"schedule_id": 1, "operating_date": "2026-11-05"},
                   headers=h).json()
    r = c.put(f"/api/trip-sheets/{sheet['sheet_id']}", headers=h, json={"crew": [
        {"crew_id": sheet["crew"][0]["crew_id"], "employee_id": stranger,
         "duty_start_day_offset": 0, "duty_start_time": "05:00",
         "duty_end_day_offset": 0, "duty_end_time": "12:00"}]})
    assert r.status_code == 422 and "another cost center" in r.text

    # the availability register too
    r = c.post("/api/employee-availability", headers=h, json={
        "employee_id": stranger, "status": "LEAVE", "from_date": "2026-11-02", "to_date": "2026-11-02"})
    assert r.status_code == 422


# --------------------------------------------------------------------------
# Spares, shunting and repeating a week
# --------------------------------------------------------------------------
def test_spares_and_shunting_are_added_per_day(world):
    c, h = world["client"], world["h"]
    _published(world)
    roster = _roster_for(world)
    rid = roster["roster_id"]
    d1, d2 = _staff(world, "D1"), _staff(world, "D2")

    # two spares and a shunting driver on the same day
    for body in ({"duty_date": "2026-11-02", "duty_type": "SPARE", "employee_id": d1},
                 {"duty_date": "2026-11-02", "duty_type": "SPARE", "employee_id": d2},
                 {"duty_date": "2026-11-02", "duty_type": "SHUNTING", "employee_id": d2,
                  "start_time": "06:00", "end_time": "14:00"}):
        r = c.post(f"/api/rosters/{rid}/extras", json=body, headers=h)
        assert r.status_code == 201, r.text
    g = r.json()

    day = g["extras"]["2026-11-02"]
    assert [x["slot_index"] for x in day["SPARE"]] == [1, 2]
    assert [x["employee_number"] for x in day["SPARE"]] == ["D1", "D2"]
    assert day["SHUNTING"][0]["start_time"] == "06:00" and day["SHUNTING"][0]["slot_index"] == 1
    assert g["extras"]["2026-11-03"]["SPARE"] == []          # only the day it was added to

    # a spare can be changed and removed
    spare = day["SPARE"][1]["extra_id"]
    g = c.put(f"/api/rosters/{rid}/extras/{spare}", json={"employee_id": d1, "remarks": "swapped"},
              headers=h).json()
    assert g["extras"]["2026-11-02"]["SPARE"][1]["employee_number"] == "D1"
    g = c.delete(f"/api/rosters/{rid}/extras/{spare}", headers=h).json()
    assert [x["slot_index"] for x in g["extras"]["2026-11-02"]["SPARE"]] == [1]


def test_spare_validation(world):
    c, h = world["client"], world["h"]
    _published(world)
    roster = _roster_for(world)
    rid = roster["roster_id"]
    d1 = _staff(world, "D1")
    cond = _staff(world, "C1", "CONDUCTOR")

    # an empty spare row is a leftover, not an error
    assert c.post(f"/api/rosters/{rid}/extras", json={"duty_date": "2026-11-02", "duty_type": "SPARE"},
                  headers=h).status_code == 201
    issues = c.post(f"/api/rosters/{rid}/validate", headers=h).json()["issues"]
    empty = [i for i in issues if i["code"] == "EXTRA_EMPTY"]
    assert len(empty) == 1 and empty[0]["severity"] == "WARNING"

    # a conductor cannot be a shunting driver
    assert c.post(f"/api/rosters/{rid}/extras", json={
        "duty_date": "2026-11-03", "duty_type": "SHUNTING", "employee_id": cond}, headers=h).status_code == 201
    codes = {i["code"] for i in c.post(f"/api/rosters/{rid}/validate", headers=h).json()["issues"]}
    assert "CREW_TYPE" in codes

    # standby and a bus on the same day is a warning: the depot may still have called them in
    assert _cells(c, h, rid, [{"duty_date": "2026-11-04", "schedule_id": 1, "crew_role": "DRIVER",
                               "employee_id": d1}]).status_code == 200
    assert c.post(f"/api/rosters/{rid}/extras", json={
        "duty_date": "2026-11-04", "duty_type": "SPARE", "employee_id": d1}, headers=h).status_code == 201
    both = [i for i in c.post(f"/api/rosters/{rid}/validate", headers=h).json()["issues"]
            if i["code"] == "EXTRA_ALSO_ON_A_BUS"]
    assert len(both) == 1 and both[0]["severity"] == "WARNING" and "S1" in both[0]["message"]


def test_repeat_first_week_across_the_period(client, admin, world):
    """One typed week becomes the whole month, and the last block stops at the period's end."""
    c, h = world["client"], world["h"]
    _published(world)
    r = c.post("/api/rosters", headers=h, json={"roster_code": "NOV-FULL", "period_from": "2026-11-01",
                                                "period_to": "2026-11-23"})
    assert r.status_code == 201, r.text
    rid = r.json()["roster_id"]
    d1 = _staff(world, "D1")
    assert _cells(c, h, rid, [{"duty_date": f"2026-11-0{d}", "schedule_id": 1, "crew_role": "DRIVER",
                               "employee_id": d1} for d in range(1, 8)]).status_code == 200

    res = c.post(f"/api/rosters/{rid}/repeat-block", json={}, headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    # 8-14, 15-21, 22-23 (cut short): 7 + 7 + 2 duties
    assert body["blocks"] == 3 and body["copied"] == 16
    cells = body["rows"][0]["cells"]
    assert all(cells[d]["employee_number"] == "D1" for d in sorted(cells))
    assert len(cells) == 23

    # repeating a named block works the same way
    res = c.post(f"/api/rosters/{rid}/repeat-block", json={"source_from": "2026-11-01", "day_count": 2},
                 headers=h).json()
    assert res["block_days"] == 2 and res["repeated_from"] == "2026-11-01"


def test_crew_options_lists_the_depots_drivers(world):
    c, h = world["client"], world["h"]
    _published(world)
    roster = _roster_for(world)
    _staff(world, "D1")
    _staff(world, "C1", "CONDUCTOR")
    _staff(world, "M1", "DEPOT_STAFF")
    on_leave = _staff(world, "D2")
    assert c.post("/api/employee-availability", headers=h, json={
        "employee_id": on_leave, "status": "LEAVE", "from_date": "2026-11-02",
        "to_date": "2026-11-04"}).status_code == 201

    r = c.get(f"/api/rosters/{roster['roster_id']}/crew-options?on=2026-11-03", headers=h)
    assert r.status_code == 200, r.text
    crew = r.json()["crew"]
    # drivers and conductors only - depot staff never take a bus duty
    assert {x["employee_number"] for x in crew} == {"C1", "D1", "D2"}
    by_number = {x["employee_number"]: x for x in crew}
    assert by_number["D1"]["free"] is True
    assert by_number["D2"]["free"] is False and "leave" in by_number["D2"]["reason"].lower()


# --------------------------------------------------------------------------
# Step 4: publish, freeze, revise
# --------------------------------------------------------------------------
def _filled_roster(world, code="NOV26P", period=("2026-11-01", "2026-11-07")):
    """A roster whose every slot is filled, so it can be published."""
    c, h = world["client"], world["h"]
    r = c.post("/api/rosters", headers=h, json={"roster_code": code, "period_from": period[0],
                                                "period_to": period[1]})
    assert r.status_code == 201, r.text
    rid = r.json()["roster_id"]
    # reuse D1 when an earlier roster in the same test already created them
    existing = {e["employee_number"]: e["employee_id"]
                for e in c.get("/api/employees", headers=h).json()}
    d1 = existing.get("D1") or _staff(world, "D1")
    g = c.get(f"/api/rosters/{rid}/grid", headers=h).json()
    cells = [{"duty_date": d, "schedule_id": row["schedule_id"], "shift_number": row["shift_number"],
              "crew_role": row["crew_role"], "employee_id": d1}
             for row in g["rows"] for d in row["cells"]]
    assert _cells(c, h, rid, cells).status_code == 200
    return rid, d1


def test_publishing_freezes_the_plan(world):
    c, h = world["client"], world["h"]
    _published(world)
    rid, d1 = _filled_roster(world)

    r = c.post(f"/api/rosters/{rid}/publish", json={}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "PUBLISHED" and r.json()["superseded"] is None

    # the frozen version cannot be edited any more, by API...
    r = _cells(c, h, rid, [{"duty_date": "2026-11-02", "schedule_id": 1, "crew_role": "DRIVER",
                            "employee_id": None}])
    assert r.status_code == 409 and "no draft version" in r.text
    # ...and the grid still reads the live version
    g = c.get(f"/api/rosters/{rid}/grid", headers=h).json()
    assert g["status"] == "PUBLISHED" and g["version_number"] == 1


def test_errors_block_publishing_and_warnings_must_be_confirmed(world):
    c, h = world["client"], world["h"]
    _published(world)
    r = c.post("/api/rosters", headers=h, json={"roster_code": "NOV-E", "period_from": "2026-11-01",
                                                "period_to": "2026-11-03"})
    rid = r.json()["roster_id"]
    assert c.post(f"/api/rosters/{rid}/publish", json={}, headers=h).status_code == 409   # unfilled

    d1 = _staff(world, "D1")
    assert _cells(c, h, rid, [{"duty_date": f"2026-11-0{d}", "schedule_id": 1, "crew_role": "DRIVER",
                               "employee_id": d1} for d in (1, 2, 3)]).status_code == 200
    # a warning: marked unavailable on one of the days
    assert c.post("/api/employee-availability", headers=h, json={
        "employee_id": d1, "status": "LEAVE", "from_date": "2026-11-02",
        "to_date": "2026-11-02"}).status_code == 201
    r = c.post(f"/api/rosters/{rid}/publish", json={}, headers=h)
    assert r.status_code == 409 and "warning" in r.json()["detail"]
    r = c.post(f"/api/rosters/{rid}/publish", json={"acknowledge_warnings": True}, headers=h)
    assert r.status_code == 200 and r.json()["warnings"] == 1


def test_a_revision_copies_the_whole_period_and_supersedes_the_old_one(world):
    c, h = world["client"], world["h"]
    _published(world)
    rid, d1 = _filled_roster(world)
    assert c.post(f"/api/rosters/{rid}/publish", json={}, headers=h).status_code == 200
    d2 = _staff(world, "D2")

    r = c.post(f"/api/rosters/{rid}/versions", json={"change_reason": "D1 off sick"}, headers=h)
    assert r.status_code == 201, r.text
    g = r.json()
    assert g["version_number"] == 2 and g["status"] == "DRAFT"
    # every day came across, not only the ones still to come
    assert all(cell["employee_number"] == "D1" for row in g["rows"] for cell in row["cells"].values())

    # only one draft at a time
    assert c.post(f"/api/rosters/{rid}/versions", json={}, headers=h).status_code == 409

    # change one day and publish: v1 becomes superseded, v2 is the only live one
    assert _cells(c, h, rid, [{"duty_date": "2026-11-05", "schedule_id": 1, "crew_role": "DRIVER",
                               "employee_id": d2}]).status_code == 200
    r = c.post(f"/api/rosters/{rid}/publish", json={}, headers=h).json()
    assert r["superseded"] == 1
    statuses = {v["version_number"]: v["status"]
                for v in c.get("/api/rosters", headers=h).json()[0]["versions"]}
    assert statuses == {1: "SUPERSEDED", 2: "PUBLISHED"}


def test_version_diff_reports_only_what_changed(world):
    c, h = world["client"], world["h"]
    _published(world)
    rid, d1 = _filled_roster(world)
    assert c.post(f"/api/rosters/{rid}/publish", json={}, headers=h).status_code == 200
    d2 = _staff(world, "D2")
    assert c.post(f"/api/rosters/{rid}/versions", json={}, headers=h).status_code == 201
    assert _cells(c, h, rid, [{"duty_date": "2026-11-05", "schedule_id": 1, "crew_role": "DRIVER",
                               "employee_id": d2},
                              {"duty_date": "2026-11-06", "schedule_id": 1, "crew_role": "DRIVER",
                               "employee_id": None}]).status_code == 200

    d = c.get(f"/api/rosters/{rid}/diff", headers=h).json()
    assert d["changes"] == 2
    by_date = {r["duty_date"]: r for r in d["rows"]}
    assert by_date["2026-11-05"]["change"] == "REPLACED"
    assert by_date["2026-11-05"]["before"]["employee_number"] == "D1"
    assert by_date["2026-11-05"]["after"]["employee_number"] == "D2"
    assert by_date["2026-11-06"]["change"] == "REMOVED" and by_date["2026-11-06"]["after"] is None


# --------------------------------------------------------------------------
# Step 3: the pattern generator
# --------------------------------------------------------------------------
def test_pattern_rotation_generates_a_draft(world):
    """Three drivers on a 3-day cycle: two duties and an off day, rotating."""
    c, h = world["client"], world["h"]
    _published(world)
    _published(world, code="S2", bus_key="bus2")
    drivers = [_staff(world, f"D{i}") for i in (1, 2, 3)]

    p = c.post("/api/duty-patterns", headers=h,
               json={"pattern_code": "ROT3", "cycle_days": 3}).json()
    pid = p["pattern_id"]
    r = c.put(f"/api/duty-patterns/{pid}/slots", headers=h, json={"slots": [
        {"cycle_day": 0, "schedule_id": 1, "crew_role": "DRIVER"},
        {"cycle_day": 1, "schedule_id": 2, "crew_role": "DRIVER"},
        {"cycle_day": 2, "schedule_id": None}]})
    assert r.status_code == 200, r.text
    assert c.put(f"/api/duty-patterns/{pid}/members", headers=h,
                 json={"employee_ids": drivers}).status_code == 200

    roster = c.post("/api/rosters", headers=h, json={"roster_code": "ROT", "period_from": "2026-11-01",
                                                     "period_to": "2026-11-06"}).json()
    rid = roster["roster_id"]
    res = c.post(f"/api/rosters/{rid}/generate", headers=h, json={"pattern_id": pid})
    assert res.status_code == 200, res.text
    body = res.json()
    # 6 days x 3 members = 18 lines, a third of them off days
    assert body["off_days"] == 6 and body["written"] == 12

    assert c.post(f"/api/rosters/{rid}/validate", headers=h).json()["errors"] == 0
    # each driver works each bus in turn and rests every third day
    rows = {r["schedule_code"]: r["cells"] for r in body["rows"]}
    # member i works cycle day (day_index + i) % 3, and S1 is cycle day 0
    assert [rows["S1"][d]["employee_number"] for d in sorted(rows["S1"])] == \
        ["D1", "D3", "D2", "D1", "D3", "D2"]
    assert all(c2["source"] == "GENERATED" for cells in rows.values() for c2 in cells.values())


def test_pattern_rules(world):
    c, h = world["client"], world["h"]
    _published(world)
    drivers = [_staff(world, f"D{i}") for i in (1, 2, 3)]
    pid = c.post("/api/duty-patterns", headers=h,
                 json={"pattern_code": "ROT2", "cycle_days": 2}).json()["pattern_id"]

    # one duty per cycle day
    r = c.put(f"/api/duty-patterns/{pid}/slots", headers=h, json={"slots": [
        {"cycle_day": 0, "schedule_id": 1, "crew_role": "DRIVER"},
        {"cycle_day": 0, "schedule_id": 1, "crew_role": "CONDUCTOR"}]})
    assert r.status_code == 422 and "already has a duty" in r.json()["detail"]
    # a cycle day outside the cycle
    r = c.put(f"/api/duty-patterns/{pid}/slots", headers=h,
              json={"slots": [{"cycle_day": 5, "schedule_id": 1, "crew_role": "DRIVER"}]})
    assert r.status_code == 422 and "outside a 2-day cycle" in r.json()["detail"]
    # a line longer than the cycle would double-book
    r = c.put(f"/api/duty-patterns/{pid}/members", headers=h, json={"employee_ids": drivers})
    assert r.status_code == 422 and "cannot be longer than the cycle" in r.json()["detail"]


def test_generate_keeps_hand_edits_unless_overwrite(world):
    c, h = world["client"], world["h"]
    _published(world)
    d1, d2 = _staff(world, "D1"), _staff(world, "D2")
    pid = c.post("/api/duty-patterns", headers=h,
                 json={"pattern_code": "ROT1", "cycle_days": 1}).json()["pattern_id"]
    c.put(f"/api/duty-patterns/{pid}/slots", headers=h,
          json={"slots": [{"cycle_day": 0, "schedule_id": 1, "crew_role": "DRIVER"}]})
    c.put(f"/api/duty-patterns/{pid}/members", headers=h, json={"employee_ids": [d1]})

    rid = c.post("/api/rosters", headers=h, json={"roster_code": "KEEP", "period_from": "2026-11-01",
                                                  "period_to": "2026-11-03"}).json()["roster_id"]
    assert _cells(c, h, rid, [{"duty_date": "2026-11-02", "schedule_id": 1, "crew_role": "DRIVER",
                               "employee_id": d2}]).status_code == 200

    body = c.post(f"/api/rosters/{rid}/generate", headers=h, json={"pattern_id": pid}).json()
    assert body["kept_manual"] == 1 and body["written"] == 2
    assert body["rows"][0]["cells"]["2026-11-02"]["employee_number"] == "D2"

    body = c.post(f"/api/rosters/{rid}/generate", headers=h,
                  json={"pattern_id": pid, "overwrite": True}).json()
    assert body["kept_manual"] == 0 and body["written"] == 3
    assert body["rows"][0]["cells"]["2026-11-02"]["employee_number"] == "D1"


# --------------------------------------------------------------------------
# Step 5: what actually happened
# --------------------------------------------------------------------------
def _live_roster(world, code="NOV26A"):
    """A published roster with one driver on every slot, plus a spare on the 2nd."""
    c, h = world["client"], world["h"]
    rid, d1 = _filled_roster(world, code=code)
    assert c.post(f"/api/rosters/{rid}/extras", headers=h, json={
        "duty_date": "2026-11-02", "duty_type": "SPARE", "employee_id": d1}).status_code == 201
    r = c.post(f"/api/rosters/{rid}/publish", json={"acknowledge_warnings": True}, headers=h)
    assert r.status_code == 200, r.text
    return rid, d1


def test_opening_a_day_snapshots_the_plan(world):
    c, h = world["client"], world["h"]
    _published(world)
    rid, d1 = _live_roster(world)

    r = c.post(f"/api/rosters/{rid}/actuals/open", json={"duty_date": "2026-11-02"}, headers=h)
    assert r.status_code == 200, r.text
    day = r.json()
    assert day["opened"] == 2                  # the bus duty and the spare
    kinds = {x["duty_type"]: x for x in day["rows"]}
    assert kinds["SCHEDULE"]["planned"]["employee_number"] == "D1"
    assert kinds["SCHEDULE"]["actual"]["employee_number"] == "D1"   # as planned until told otherwise
    assert kinds["SCHEDULE"]["status"] == "AS_PLANNED"
    assert kinds["SPARE"]["slot_label"] == "Spare 1"

    # opening again adds nothing and loses nothing
    again = c.post(f"/api/rosters/{rid}/actuals/open", json={"duty_date": "2026-11-02"}, headers=h).json()
    assert again["opened"] == 0 and again["already_open"] == 2


def test_recording_a_replacement_and_an_absence(world):
    c, h = world["client"], world["h"]
    _published(world)
    rid, d1 = _live_roster(world)
    d2 = _staff(world, "D2")
    day = c.post(f"/api/rosters/{rid}/actuals/open", json={"duty_date": "2026-11-03"},
                 headers=h).json()
    slot = day["rows"][0]["actual_id"]
    reason = c.get("/api/trip-reasons", headers=h).json()[0]["reason_id"]

    # a change from the plan has to say why
    r = c.put(f"/api/rosters/{rid}/actuals/{slot}", headers=h,
              json={"status": "REPLACED", "actual_employee_id": d2})
    assert r.status_code == 422 and "reason" in r.json()["detail"]

    r = c.put(f"/api/rosters/{rid}/actuals/{slot}", headers=h,
              json={"status": "REPLACED", "actual_employee_id": d2, "reason_id": reason})
    assert r.status_code == 200, r.text
    row = r.json()["rows"][0]
    assert row["status"] == "REPLACED"
    assert row["planned"]["employee_number"] == "D1" and row["actual"]["employee_number"] == "D2"

    # nobody worked it: the status follows from that, whatever was asked for
    r = c.put(f"/api/rosters/{rid}/actuals/{slot}", headers=h,
              json={"status": "AS_PLANNED", "actual_employee_id": None, "reason_id": reason}).json()
    assert r["rows"][0]["status"] == "ABSENT" and r["rows"][0]["actual"] is None
    assert r["counts"]["ABSENT"] == 1


def test_closing_a_day_locks_it_and_reopening_needs_a_reason(world):
    c, h = world["client"], world["h"]
    _published(world)
    rid, d1 = _live_roster(world)
    c.post(f"/api/rosters/{rid}/actuals/open", json={"duty_date": "2026-11-04"}, headers=h)

    r = c.post(f"/api/rosters/{rid}/actuals/close", json={"duty_date": "2026-11-04"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["locked_through"] == "2026-11-04"

    day = c.get(f"/api/rosters/{rid}/actuals/2026-11-04", headers=h).json()
    assert day["locked"] is True
    slot = day["rows"][0]["actual_id"]
    r = c.put(f"/api/rosters/{rid}/actuals/{slot}", headers=h,
              json={"status": "ABSENT", "remarks": "late"})
    assert r.status_code == 409 and "closed" in r.json()["detail"]

    assert c.post(f"/api/rosters/{rid}/actuals/reopen", json={"duty_date": "2026-11-04"},
                  headers=h).status_code == 422          # no reason
    r = c.post(f"/api/rosters/{rid}/actuals/reopen", headers=h,
               json={"duty_date": "2026-11-04", "reason": "wrong driver keyed"})
    assert r.status_code == 200, r.text
    assert r.json()["locked_through"] == "2026-11-03"
    assert c.put(f"/api/rosters/{rid}/actuals/{slot}", headers=h,
                 json={"status": "ABSENT", "remarks": "late"}).status_code == 200


def test_a_revision_carries_closed_days_over_untouched(world):
    c, h = world["client"], world["h"]
    _published(world)
    rid, d1 = _live_roster(world)
    d2 = _staff(world, "D2")
    c.post(f"/api/rosters/{rid}/actuals/open", json={"duty_date": "2026-11-01"}, headers=h)
    assert c.post(f"/api/rosters/{rid}/actuals/close", json={"duty_date": "2026-11-01"},
                  headers=h).status_code == 200

    g = c.post(f"/api/rosters/{rid}/versions", json={"change_reason": "new driver"}, headers=h).json()
    closed = g["rows"][0]["cells"]["2026-11-01"]
    assert closed["source"] == "CARRIED" and closed["locked"] is True
    # and the locked day cannot be changed in the new version either
    r = _cells(c, h, rid, [{"duty_date": "2026-11-01", "schedule_id": 1, "crew_role": "DRIVER",
                            "employee_id": d2}])
    assert r.status_code == 409 and "closed" in r.json()["detail"]
    # a later day still can be
    assert _cells(c, h, rid, [{"duty_date": "2026-11-06", "schedule_id": 1, "crew_role": "DRIVER",
                               "employee_id": d2}]).status_code == 200


def test_unpublish_is_refused_once_the_plan_has_been_worked_to(world):
    c, h = world["client"], world["h"]
    _published(world)
    rid, d1 = _live_roster(world)
    c.post(f"/api/rosters/{rid}/actuals/open", json={"duty_date": "2026-11-02"}, headers=h)
    r = c.post(f"/api/rosters/{rid}/unpublish", headers=h)
    assert r.status_code == 409 and "actuals recorded" in r.json()["detail"]


# --------------------------------------------------------------------------
# Step 6: the roster fills a trip sheet's crew
# --------------------------------------------------------------------------
def test_trip_sheet_crew_comes_from_the_roster(world):
    c, h = world["client"], world["h"]
    _published(world)
    rid, d1 = _live_roster(world)

    sheet = c.post("/api/trip-sheets", json={"schedule_id": 1, "operating_date": "2026-11-05"},
                   headers=h).json()
    assert [x["employee_number"] for x in sheet["crew"]] == ["D1"]

    # somebody else actually drove: the sheet keeps it, and says it differs from the roster
    d2 = _staff(world, "D2")
    r = c.put(f"/api/trip-sheets/{sheet['sheet_id']}", headers=h, json={"crew": [
        {"crew_id": sheet["crew"][0]["crew_id"], "employee_id": d2,
         "duty_start_day_offset": 0, "duty_start_time": "05:00",
         "duty_end_day_offset": 1, "duty_end_time": "04:30"}]})
    assert r.status_code == 200, r.text
    issues = c.post(f"/api/trip-sheets/{sheet['sheet_id']}/validate", headers=h).json()["issues"]
    off = [i for i in issues if i["code"] == "CREW_OFF_ROSTER"]
    assert len(off) == 1 and off[0]["severity"] == "WARNING"
    assert "Staff D2 worked it" in off[0]["message"] and "Staff D1" in off[0]["message"]


# --------------------------------------------------------------------------
# Steps 7 and 8: the summary, the statistics and the board
# --------------------------------------------------------------------------
def test_day_summary_and_statistics(world):
    c, h = world["client"], world["h"]
    _published(world)
    rid, d1 = _live_roster(world)
    d2 = _staff(world, "D2")
    reason = c.get("/api/trip-reasons", headers=h).json()[0]["reason_id"]

    day = c.post(f"/api/rosters/{rid}/actuals/open", json={"duty_date": "2026-11-02"},
                 headers=h).json()
    bus = [x for x in day["rows"] if x["duty_type"] == "SCHEDULE"][0]["actual_id"]
    c.put(f"/api/rosters/{rid}/actuals/{bus}", headers=h,
          json={"status": "REPLACED", "actual_employee_id": d2, "reason_id": reason})

    rep = c.get("/api/reports/duty-day?on=2026-11-02", headers=h).json()
    assert rep["slots"] == 2 and rep["changed"] == 1
    assert rep["counts"]["REPLACED"] == 1 and rep["counts"]["AS_PLANNED"] == 1
    assert rep["as_planned_pct"] == 50.0

    stats = c.get("/api/reports/duty-statistics?date_from=2026-11-01&date_to=2026-11-07",
                  headers=h).json()
    by_number = {x["employee_number"]: x for x in stats["crew"]}
    assert by_number["D1"]["planned"] == 2 and by_number["D1"]["missed"] == 1
    assert by_number["D2"]["worked"] == 1 and by_number["D2"]["stood_in"] == 1
    assert by_number["D1"]["spare"] == 1
    assert stats["top_reasons"][0]["count"] == 1
    # hours count the stretch each person held, so a part-duty is not a whole one
    assert by_number["D2"]["minutes"] > 0

    # the board shows every day's state at a glance
    board = c.get(f"/api/rosters/{rid}/actuals", headers=h).json()
    days = {d["duty_date"]: d for d in board["days"]}
    assert days["2026-11-02"]["open"] is True and days["2026-11-02"]["changed"] == 1
    assert days["2026-11-03"]["open"] is False

    # and both reports download as Excel
    for url in ("/api/reports/duty-day.xlsx?on=2026-11-02",
                "/api/reports/duty-statistics.xlsx?date_from=2026-11-01&date_to=2026-11-07"):
        r = c.get(url, headers=h)
        assert r.status_code == 200 and r.content[:2] == b"PK", url


def test_a_draft_roster_can_be_deleted_but_a_published_one_cannot(world):
    c, h = world["client"], world["h"]
    _published(world)
    rid, d1 = _filled_roster(world, code="GONE")
    assert c.delete(f"/api/rosters/{rid}", headers=h).status_code == 204
    assert "GONE" not in {r["roster_code"] for r in c.get("/api/rosters", headers=h).json()}

    rid, _ = _filled_roster(world, code="KEPT")
    assert c.post(f"/api/rosters/{rid}/publish", json={}, headers=h).status_code == 200
    r = c.delete(f"/api/rosters/{rid}", headers=h)
    assert r.status_code == 409 and "cannot be deleted" in r.json()["detail"]


# --------------------------------------------------------------------------
# Validating what was recorded, not only what was planned
# --------------------------------------------------------------------------
def test_a_replacement_cannot_be_in_two_places_at_once(world):
    """The clerk sees the bus in front of them, not what that driver was already down for."""
    c, h = world["client"], world["h"]
    _published(world)
    _published(world, code="S2", bus_key="bus2")
    rid, d1 = _filled_roster(world, code="CLASH")           # D1 on both buses would not publish
    d2 = _staff(world, "D2")
    g = c.get(f"/api/rosters/{rid}/grid", headers=h).json()
    s2 = next(r for r in g["rows"] if r["schedule_code"] == "S2")
    assert _cells(c, h, rid, [{"duty_date": d, "schedule_id": s2["schedule_id"],
                               "crew_role": "DRIVER", "employee_id": d2}
                              for d in s2["cells"]]).status_code == 200
    assert c.post(f"/api/rosters/{rid}/publish", json={}, headers=h).status_code == 200

    day = c.post(f"/api/rosters/{rid}/actuals/open", json={"duty_date": "2026-11-03"},
                 headers=h).json()
    assert day["validation"]["errors"] == 0                 # as planned: one driver each
    reason = c.get("/api/trip-reasons", headers=h).json()[0]["reason_id"]

    # D2 did not turn up for S2, and D1 - already driving S1 all day - is recorded instead
    s2_slot = next(r["actual_id"] for r in day["rows"] if r["schedule_code"] == "S2")
    r = c.put(f"/api/rosters/{rid}/actuals/{s2_slot}", headers=h,
              json={"status": "REPLACED", "actual_employee_id": d1, "reason_id": reason})
    assert r.status_code == 200, r.text
    v = r.json()["validation"]
    clash = [i for i in v["issues"] if i["code"] == "ACTUAL_DOUBLE_BOOKED"]
    assert len(clash) == 1 and clash[0]["severity"] == "ERROR"
    assert "the two overlap" in clash[0]["message"]
    assert v["can_close"] is False

    # and the day cannot be closed while the record says that
    r = c.post(f"/api/rosters/{rid}/actuals/close", json={"duty_date": "2026-11-03"}, headers=h)
    assert r.status_code == 409 and "ACTUAL" not in r.json()["detail"]
    assert "overlap" in r.json()["detail"]

    # recording somebody who was free clears it
    d3 = _staff(world, "D3")
    r = c.put(f"/api/rosters/{rid}/actuals/{s2_slot}", headers=h,
              json={"status": "REPLACED", "actual_employee_id": d3, "reason_id": reason}).json()
    assert r["validation"]["errors"] == 0 and r["validation"]["can_close"] is True
    assert c.post(f"/api/rosters/{rid}/actuals/close", json={"duty_date": "2026-11-03"},
                  headers=h).status_code == 200


def test_actual_validation_also_checks_the_person(world):
    c, h = world["client"], world["h"]
    _published(world)
    rid, d1 = _filled_roster(world, code="CHECKS")
    assert c.post(f"/api/rosters/{rid}/publish", json={}, headers=h).status_code == 200
    # marked on leave, but worked anyway: a warning, because that is what happened
    assert c.post("/api/employee-availability", headers=h, json={
        "employee_id": d1, "status": "LEAVE", "from_date": "2026-11-02",
        "to_date": "2026-11-02"}).status_code == 201

    day = c.post(f"/api/rosters/{rid}/actuals/open", json={"duty_date": "2026-11-02"},
                 headers=h).json()
    codes = {i["code"]: i["severity"] for i in day["validation"]["issues"]}
    assert codes.get("ACTUAL_UNAVAILABLE") == "WARNING"
    assert day["validation"]["can_close"] is True            # a warning never blocks

    # an uncovered duty is reported too
    slot = day["rows"][0]["actual_id"]
    r = c.put(f"/api/rosters/{rid}/actuals/{slot}", headers=h,
              json={"status": "ABSENT", "actual_employee_id": None, "remarks": "no stand-in"}).json()
    assert "ACTUAL_UNCOVERED" in {i["code"] for i in r["validation"]["issues"]}

    # the standalone endpoint gives the same answer
    v = c.get(f"/api/rosters/{rid}/actuals/2026-11-02/validate", headers=h).json()
    assert "ACTUAL_UNCOVERED" in {i["code"] for i in v["issues"]}


# --------------------------------------------------------------------------
# Spares: idle, covering a whole duty, and taking over mid-duty
# --------------------------------------------------------------------------
def _with_spare(world, code):
    """A published roster with a driver on the bus and a spare on standby all week."""
    c, h = world["client"], world["h"]
    rid, d1 = _filled_roster(world, code=code)
    spare = _staff(world, "D9")
    for day in ("2026-11-02", "2026-11-03"):
        assert c.post(f"/api/rosters/{rid}/extras", headers=h, json={
            "duty_date": day, "duty_type": "SPARE", "employee_id": spare}).status_code == 201
    assert c.post(f"/api/rosters/{rid}/publish", json={}, headers=h).status_code == 200
    return rid, d1, spare


def test_scenario_1_spare_stands_by_and_is_not_called(world):
    c, h = world["client"], world["h"]
    _published(world)
    rid, d1, spare = _with_spare(world, "SP1")

    day = c.post(f"/api/rosters/{rid}/actuals/open", json={"duty_date": "2026-11-02"},
                 headers=h).json()
    spare_row = next(r for r in day["rows"] if r["duty_type"] == "SPARE")
    assert spare_row["status"] == "AS_PLANNED"
    assert spare_row["actual"]["employee_number"] == "D9"
    assert spare_row["called_out_to"] is None          # stood by, never used
    assert day["validation"]["errors"] == 0 and day["validation"]["warnings"] == 0


def test_scenario_2_spare_covers_the_whole_duty(world):
    c, h = world["client"], world["h"]
    _published(world)
    rid, d1, spare = _with_spare(world, "SP2")
    reason = c.get("/api/trip-reasons", headers=h).json()[0]["reason_id"]

    day = c.post(f"/api/rosters/{rid}/actuals/open", json={"duty_date": "2026-11-02"},
                 headers=h).json()
    bus = next(r["actual_id"] for r in day["rows"] if r["duty_type"] == "SCHEDULE")
    day = c.put(f"/api/rosters/{rid}/actuals/{bus}", headers=h,
                json={"status": "REPLACED", "actual_employee_id": spare,
                      "reason_id": reason}).json()

    bus_row = next(r for r in day["rows"] if r["duty_type"] == "SCHEDULE")
    assert bus_row["status"] == "REPLACED" and bus_row["actual"]["employee_number"] == "D9"
    spare_row = next(r for r in day["rows"] if r["duty_type"] == "SPARE")
    assert spare_row["called_out_to"] == "S1"          # the standby row says where they went
    # being a called-out spare and driving is not an anomaly
    codes = {i["code"] for i in day["validation"]["issues"]}
    assert "ACTUAL_ALSO_SPARE" not in codes and day["validation"]["errors"] == 0


def test_scenario_3_spare_takes_over_mid_duty(world):
    """The driver has to leave; the spare finishes the duty."""
    c, h = world["client"], world["h"]
    _published(world)
    rid, d1, spare = _with_spare(world, "SP3")
    reason = c.get("/api/trip-reasons", headers=h).json()[0]["reason_id"]

    day = c.post(f"/api/rosters/{rid}/actuals/open", json={"duty_date": "2026-11-02"},
                 headers=h).json()
    bus = next(r for r in day["rows"] if r["duty_type"] == "SCHEDULE")
    assert bus["from_time"] and bus["to_time"]         # the duty's hours came from the plan
    assert bus["segments"] == 1

    r = c.post(f"/api/rosters/{rid}/actuals/{bus['actual_id']}/handover", headers=h, json={
        "at_time": "07:00", "employee_id": spare, "reason_id": reason,
        "handover_reason": "driver taken ill"})
    assert r.status_code == 201, r.text
    day = r.json()

    parts = sorted([x for x in day["rows"] if x["duty_type"] == "SCHEDULE"],
                   key=lambda x: x["segment"])
    assert [p["segment"] for p in parts] == [0, 1]
    assert parts[0]["status"] == "HANDED_OVER" and parts[0]["actual"]["employee_number"] == "D1"
    assert parts[0]["to_time"] == "07:00" and parts[0]["handover_reason"] == "driver taken ill"
    assert parts[1]["status"] == "TOOK_OVER" and parts[1]["actual"]["employee_number"] == "D9"
    assert parts[1]["from_time"] == "07:00" and parts[1]["took_over_from"] == parts[0]["actual_id"]
    # the planned driver stays on both segments, so the duty is still theirs for reporting
    assert all(p["planned"]["employee_number"] == "D1" for p in parts)
    # the two stretches add up to the duty, and neither clashes with the spare's standby
    assert parts[0]["minutes"] + parts[1]["minutes"] == bus["minutes"]
    assert day["validation"]["errors"] == 0

    # a handover needs a reason, and must fall inside the duty
    r = c.post(f"/api/rosters/{rid}/actuals/{parts[1]['actual_id']}/handover", headers=h,
               json={"at_time": "07:30", "employee_id": d1})
    assert r.status_code == 422 and "reason" in r.json()["detail"]
    r = c.post(f"/api/rosters/{rid}/actuals/{parts[1]['actual_id']}/handover", headers=h,
               json={"at_time": "04:00", "employee_id": d1, "reason_id": reason})
    assert r.status_code == 422 and "must fall inside the duty" in r.json()["detail"]
    # and only the last segment can be handed over again
    r = c.post(f"/api/rosters/{rid}/actuals/{parts[0]['actual_id']}/handover", headers=h,
               json={"at_time": "06:00", "employee_id": d1, "reason_id": reason})
    assert r.status_code == 409 and "already handed over" in r.json()["detail"]


def test_a_second_takeover_chains_and_can_be_undone(world):
    c, h = world["client"], world["h"]
    _published(world)
    rid, d1, spare = _with_spare(world, "SP4")
    d3 = _staff(world, "D3")
    reason = c.get("/api/trip-reasons", headers=h).json()[0]["reason_id"]
    day = c.post(f"/api/rosters/{rid}/actuals/open", json={"duty_date": "2026-11-03"},
                 headers=h).json()
    bus = next(r for r in day["rows"] if r["duty_type"] == "SCHEDULE")

    day = c.post(f"/api/rosters/{rid}/actuals/{bus['actual_id']}/handover", headers=h, json={
        "at_time": "07:00", "employee_id": spare, "reason_id": reason}).json()
    second = next(x for x in day["rows"] if x.get("segment") == 1)
    day = c.post(f"/api/rosters/{rid}/actuals/{second['actual_id']}/handover", headers=h, json={
        "at_time": "08:00", "employee_id": d3, "reason_id": reason}).json()

    parts = sorted([x for x in day["rows"] if x["duty_type"] == "SCHEDULE"], key=lambda x: x["segment"])
    assert [p["actual"]["employee_number"] for p in parts] == ["D1", "D9", "D3"]
    assert [p["status"] for p in parts] == ["HANDED_OVER", "HANDED_OVER", "TOOK_OVER"]
    assert day["validation"]["errors"] == 0

    # undo takes the duty back to the previous holder, last segment first
    r = c.delete(f"/api/rosters/{rid}/actuals/{parts[1]['actual_id']}/handover", headers=h)
    assert r.status_code == 409 and "undo that first" in r.json()["detail"]
    day = c.delete(f"/api/rosters/{rid}/actuals/{parts[2]['actual_id']}/handover", headers=h).json()
    parts = sorted([x for x in day["rows"] if x["duty_type"] == "SCHEDULE"], key=lambda x: x["segment"])
    assert [p["actual"]["employee_number"] for p in parts] == ["D1", "D9"]
    assert parts[1]["status"] == "TOOK_OVER" and parts[1]["to_time"] == bus["to_time"]


def test_a_takeover_by_somebody_already_driving_is_an_error(world):
    """Segments are checked by the hours they cover, not the whole duty."""
    c, h = world["client"], world["h"]
    _published(world)
    _published(world, code="S2", bus_key="bus2")
    rid, d1 = _filled_roster(world, code="SEG")
    d2 = _staff(world, "D2")
    g = c.get(f"/api/rosters/{rid}/grid", headers=h).json()
    s2 = next(r for r in g["rows"] if r["schedule_code"] == "S2")
    assert _cells(c, h, rid, [{"duty_date": d, "schedule_id": s2["schedule_id"],
                               "crew_role": "DRIVER", "employee_id": d2} for d in s2["cells"]]).status_code == 200
    assert c.post(f"/api/rosters/{rid}/publish", json={}, headers=h).status_code == 200
    reason = c.get("/api/trip-reasons", headers=h).json()[0]["reason_id"]

    day = c.post(f"/api/rosters/{rid}/actuals/open", json={"duty_date": "2026-11-03"},
                 headers=h).json()
    s1_row = next(r for r in day["rows"] if r["schedule_code"] == "S1")
    # D2 is driving S2 all day, so they cannot also finish S1
    day = c.post(f"/api/rosters/{rid}/actuals/{s1_row['actual_id']}/handover", headers=h, json={
        "at_time": "07:00", "employee_id": d2, "reason_id": reason}).json()
    clash = [i for i in day["validation"]["issues"] if i["code"] == "ACTUAL_DOUBLE_BOOKED"]
    assert len(clash) == 1 and "overlap" in clash[0]["message"]
    assert day["validation"]["can_close"] is False


def test_the_board_marks_a_sheet_whose_driver_is_not_the_rostered_one(world):
    """The clerk should see the disagreement without opening the sheet."""
    c, h = world["client"], world["h"]
    _published(world)
    rid, d1, spare = _with_spare(world, "BOARD")
    d2 = _staff(world, "D2")

    sheet = c.post("/api/trip-sheets", json={"schedule_id": 1, "operating_date": "2026-11-02"},
                   headers=h).json()
    assert sheet["crew"][0]["employee_number"] == "D1"          # pre-filled from the roster
    assert sheet["roster_crew"]["mismatch"] is False

    board = c.get("/api/trip-sheets/board?date=2026-11-02", headers=h).json()
    row = next(r for r in board if r["schedule_code"] == "S1")
    assert row["crew_mismatch"] is False

    # somebody the roster does not have on that bus is keyed onto the sheet
    assert c.put(f"/api/trip-sheets/{sheet['sheet_id']}", headers=h, json={"crew": [
        {"crew_id": sheet["crew"][0]["crew_id"], "employee_id": d2,
         "duty_start_day_offset": 0, "duty_start_time": "05:00",
         "duty_end_day_offset": 0, "duty_end_time": "08:45"}]}).status_code == 200

    board = c.get("/api/trip-sheets/board?date=2026-11-02", headers=h).json()
    row = next(r for r in board if r["schedule_code"] == "S1")
    assert row["crew_mismatch"] is True
    assert "sheet has Staff D2" in row["crew_mismatch_text"]
    assert "duty roster has Staff D1" in row["crew_mismatch_text"]

    detail = c.get(f"/api/trip-sheets/{sheet['sheet_id']}", headers=h).json()
    assert detail["roster_crew"]["mismatch"] is True
    assert detail["roster_crew"]["rows"][0]["sheet_name"] == "Staff D2"


def test_either_half_of_a_handed_over_duty_matches_the_sheet(world):
    """A duty handed over part-way was held by two people, so the sheet may name either."""
    c, h = world["client"], world["h"]
    _published(world)
    rid, d1, spare = _with_spare(world, "BOARD2")
    reason = c.get("/api/trip-reasons", headers=h).json()[0]["reason_id"]

    day = c.post(f"/api/rosters/{rid}/actuals/open", json={"duty_date": "2026-11-02"},
                 headers=h).json()
    bus = next(r for r in day["rows"] if r["duty_type"] == "SCHEDULE")
    c.post(f"/api/rosters/{rid}/actuals/{bus['actual_id']}/handover", headers=h, json={
        "at_time": "07:00", "employee_id": spare, "reason_id": reason})

    sheet = c.post("/api/trip-sheets", json={"schedule_id": 1, "operating_date": "2026-11-02"},
                   headers=h).json()
    assert sheet["crew"][0]["employee_number"] == "D1"          # the first stretch
    board = c.get("/api/trip-sheets/board?date=2026-11-02", headers=h).json()
    assert next(r for r in board if r["schedule_code"] == "S1")["crew_mismatch"] is False

    # the spare who finished the duty is just as valid a name on the sheet
    assert c.put(f"/api/trip-sheets/{sheet['sheet_id']}", headers=h, json={"crew": [
        {"crew_id": sheet["crew"][0]["crew_id"], "employee_id": spare,
         "duty_start_day_offset": 0, "duty_start_time": "05:00",
         "duty_end_day_offset": 0, "duty_end_time": "08:45"}]}).status_code == 200
    board = c.get("/api/trip-sheets/board?date=2026-11-02", headers=h).json()
    assert next(r for r in board if r["schedule_code"] == "S1")["crew_mismatch"] is False


# --------------------------------------------------------------------------
# The grid with the actuals laid over it
# --------------------------------------------------------------------------
def test_the_grid_can_show_the_plan_against_what_happened(world):
    c, h = world["client"], world["h"]
    _published(world)
    rid, d1, spare = _with_spare(world, "OVER")
    reason = c.get("/api/trip-reasons", headers=h).json()[0]["reason_id"]

    # plain: the plan only, with nothing about the day
    g = c.get(f"/api/rosters/{rid}/grid", headers=h).json()
    assert g["with_actuals"] is False
    assert "recorded" not in g["rows"][0]["cells"]["2026-11-02"]

    # 2-Nov: the planned driver was replaced; 3-Nov: handed over part-way
    day = c.post(f"/api/rosters/{rid}/actuals/open", json={"duty_date": "2026-11-02"},
                 headers=h).json()
    bus = next(r["actual_id"] for r in day["rows"] if r["duty_type"] == "SCHEDULE")
    c.put(f"/api/rosters/{rid}/actuals/{bus}", headers=h,
          json={"status": "REPLACED", "actual_employee_id": spare, "reason_id": reason})
    day = c.post(f"/api/rosters/{rid}/actuals/open", json={"duty_date": "2026-11-03"},
                 headers=h).json()
    bus3 = next(r["actual_id"] for r in day["rows"] if r["duty_type"] == "SCHEDULE")
    c.post(f"/api/rosters/{rid}/actuals/{bus3}/handover", headers=h, json={
        "at_time": "07:00", "employee_id": spare, "reason_id": reason})

    g = c.get(f"/api/rosters/{rid}/grid?actuals=true", headers=h).json()
    assert g["with_actuals"] is True
    assert g["recorded_days"] == ["2026-11-02", "2026-11-03"]
    cells = next(r for r in g["rows"] if r["schedule_code"] == "S1")["cells"]

    # a replacement: the plan and the person who worked it, side by side in the cell
    replaced = cells["2026-11-02"]
    assert replaced["employee_number"] == "D1"            # still what was planned
    assert replaced["recorded"] is True and replaced["actual_status"] == "REPLACED"
    assert [a["employee_number"] for a in replaced["actual"]] == ["D9"]

    # a handover: both names and when the change happened
    handed = cells["2026-11-03"]
    assert handed["actual_status"] == "HANDED_OVER"
    assert [(a["employee_number"], a["from_time"], a["to_time"]) for a in handed["actual"]] == [
        ("D1", "05:00", "07:00"), ("D9", "07:00", "08:45")]

    # a day nobody recorded carries the plan and says so
    untouched = cells["2026-11-04"]
    assert untouched["recorded"] is False and untouched["actual"] == []

    # the spare's own row shows what it was used for too
    spare_row = g["extras"]["2026-11-02"]["SPARE"][0]
    assert spare_row["recorded"] is True and spare_row["actual"][0]["employee_number"] == "D9"
