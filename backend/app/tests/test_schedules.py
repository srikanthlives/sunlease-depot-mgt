import pytest

from .conftest import add, codes, make_schedule, trip_body, validate


def movement(w, o, d, start, end, km=5, purpose="DEPOT_POSITIONING", pay="NON_PAYABLE", **kw):
    return {"activity_type": "NON_REVENUE_MOVEMENT", "origin_location_id": w["loc"][o], "destination_location_id": w["loc"][d],
            "scheduled_start_time": start, "scheduled_end_time": end, **kw,
            "movement": {"movement_purpose": purpose, "planned_distance_km": km, "payability_status": pay}}


def layover(w, loc, start, end, so=0, eo=0, purpose="INTER_TRIP"):
    return {"activity_type": "LAYOVER", "origin_location_id": w["loc"][loc], "destination_location_id": w["loc"][loc],
            "start_day_offset": so, "scheduled_start_time": start, "end_day_offset": eo, "scheduled_end_time": end,
            "layover": {"location_id": w["loc"][loc], "layover_purpose": purpose}}


def charging(w, loc, start, end, so=0, eo=0):
    return {"activity_type": "CHARGING", "origin_location_id": w["loc"][loc], "destination_location_id": w["loc"][loc],
            "start_day_offset": so, "scheduled_start_time": start, "end_day_offset": eo, "scheduled_end_time": end,
            "charging": {"charging_location_id": w["loc"][loc], "planned_start_soc_pct": 20, "planned_end_soc_pct": 90}}


def build_good(w, vid, base="06:00"):
    assert add(w, vid, movement(w, "DEP", "TA", "05:00", "05:40")).status_code == 201
    r = add(w, vid, trip_body(w, "up", "T1", "06:00", "06:20", "06:22", "06:50"))
    assert r.status_code == 201, r.text
    assert add(w, vid, layover(w, "TB", "06:50", "07:10")).status_code == 201
    r = add(w, vid, trip_body(w, "down", "T2", "07:10", "07:30", "07:32", "08:05"))
    assert r.status_code == 201, r.text
    assert add(w, vid, movement(w, "TA", "DEP", "08:05", "08:45", purpose="RETURN_TO_DEPOT")).status_code == 201


def test_normal_schedule_validates_and_publishes(world):
    s, vid = make_schedule(world)
    build_good(world, vid)
    res = validate(world, vid)
    assert res["valid"], res["issues"]
    assert res["summary"]["trip_count"] == 2
    assert res["summary"]["revenue_km"] == 20.5      # 10 up + 10.5 down
    r = world["client"].post(f"/api/schedule-versions/{vid}/publish", json={}, headers=world["h"])
    assert r.status_code == 200, r.text
    assert r.json()["version"]["status"] == "PUBLISHED"


def test_published_version_is_immutable(world, db):
    s, vid = make_schedule(world)
    build_good(world, vid)
    c, h = world["client"], world["h"]
    assert c.post(f"/api/schedule-versions/{vid}/publish", json={}, headers=h).status_code == 200
    detail = c.get(f"/api/schedule-versions/{vid}", headers=h).json()
    aid = detail["activities"][0]["activity_id"]
    # API level
    assert add(world, vid, layover(world, "TA", "09:00", "09:30")).status_code == 409
    assert c.delete(f"/api/activities/{aid}", headers=h).status_code == 409
    assert c.put(f"/api/schedule-versions/{vid}", json={"change_reason": "x"}, headers=h).status_code == 409
    # database level (UI/API bypassed)
    from sqlalchemy import text
    from sqlalchemy.exc import DatabaseError
    for stmt in ("UPDATE scheduled_activities SET remarks='hack' WHERE activity_id=%d" % aid,
                 "DELETE FROM scheduled_activities WHERE activity_id=%d" % aid,
                 "UPDATE scheduled_movements SET planned_distance_km=99 WHERE activity_id=%d" % aid):
        with pytest.raises(DatabaseError):
            db.execute(text(stmt))
            db.commit()
        db.rollback()


def test_midnight_crossing_duration_uses_full_timestamps(world):
    s, vid = make_schedule(world)
    # overnight layover 22:30 day0 -> 04:30 day1: 6 hours, not negative
    assert add(world, vid, layover(world, "DEP", "22:30", "04:30", eo=1, purpose="OVERNIGHT_PARKING")).status_code == 201
    tl = world["client"].get(f"/api/schedule-versions/{vid}/timeline?date=2026-11-01", headers=world["h"]).json()
    a = tl["activities"][0]
    assert a["duration_minutes"] == 360
    assert a["start_date"] == "2026-11-01" and a["end_date"] == "2026-11-02"
    # forgetting the offset is an error, not a silent +1
    bad = layover(world, "DEP", "22:30", "04:30")
    bad["layover"]["layover_purpose"] = "OTHER"
    add(world, vid, {**bad, "sequence_number": 5})
    assert "DURATION" in codes(validate(world, vid), "ERROR")


def test_trip_crossing_midnight_and_day2(world):
    s, vid = make_schedule(world)
    # trip starts 23:30 on day 1 (offset 1) and ends 00:10 on day 2 (offset 2)
    body = trip_body(world, "up", "N1", "23:30", "23:50", "23:52", "00:10", start_off=1, end_off=2)
    r = add(world, vid, body)
    assert r.status_code == 201, r.text
    res = validate(world, vid)
    assert not (codes(res, "ERROR") & {"STOP_CHRONO", "STOP_START_MISMATCH", "STOP_END_MISMATCH", "DURATION"}), res["issues"]
    tl = world["client"].get(f"/api/schedule-versions/{vid}/timeline?date=2026-11-01", headers=world["h"]).json()
    a = tl["activities"][0]
    assert a["start_date"] == "2026-11-02" and a["end_date"] == "2026-11-03" and a["duration_minutes"] == 40
    assert a["trip"]["stops"][2]["arrival_date"] == "2026-11-03"


def test_overlap_gap_and_continuity_detected(world):
    s, vid = make_schedule(world)
    add(world, vid, movement(world, "DEP", "TA", "05:00", "05:40"))
    add(world, vid, layover(world, "TA", "05:30", "06:00"))                     # overlaps previous by 10 min
    add(world, vid, layover(world, "TA", "08:00", "08:30"))                     # 2h gap
    add(world, vid, layover(world, "TB", "08:30", "09:00"))                     # location jump
    res = validate(world, vid)
    assert "OVERLAP" in codes(res, "ERROR")
    assert {"GAP", "LOCATION_JUMP"} <= codes(res, "WARNING")
    r = world["client"].post(f"/api/schedule-versions/{vid}/publish", json={"acknowledge_warnings": True}, headers=world["h"])
    assert r.status_code == 422   # errors always block


def test_warnings_need_acknowledgement(world):
    s, vid = make_schedule(world)
    add(world, vid, movement(world, "DEP", "TA", "05:00", "05:40"))
    add(world, vid, layover(world, "TA", "08:00", "08:30"))                     # gap warning only
    c, h = world["client"], world["h"]
    res = validate(world, vid)
    assert res["valid"] and res["warning_count"] >= 1
    r = c.post(f"/api/schedule-versions/{vid}/publish", json={}, headers=h)
    assert r.status_code == 422 and r.json()["detail"]["needs_acknowledgement"]
    assert c.post(f"/api/schedule-versions/{vid}/publish", json={"acknowledge_warnings": True}, headers=h).status_code == 200


def test_charging_requires_charging_capable_location_and_is_stationary(world):
    s, vid = make_schedule(world)
    add(world, vid, charging(world, "TA", "09:00", "11:00"))         # TA cannot charge
    assert "CHARGER_UNSUPPORTED" in codes(validate(world, vid), "ERROR")
    # movement to the charger is a separate activity
    s2, vid2 = make_schedule(world, "S2", "bus2")
    add(world, vid2, movement(world, "TA", "CHG", "08:30", "09:00", purpose="CHARGING_ACCESS", pay="TO_BE_CONFIRMED"))
    add(world, vid2, charging(world, "CHG", "09:00", "11:00"))
    res = validate(world, vid2)
    assert res["valid"], res["issues"]
    bad = charging(world, "CHG", "11:00", "12:00")
    bad["destination_location_id"] = world["loc"]["DEP"]            # charging that "moves"
    add(world, vid2, bad)
    assert "CHARGING_LOCATION" in codes(validate(world, vid2), "ERROR")


def test_movement_purpose_and_payability_are_independent(world):
    s, vid = make_schedule(world)
    for pay in ("PAYABLE", "NON_PAYABLE", "TO_BE_CONFIRMED"):
        r = add(world, vid, movement(world, "DEP", "CHG", "05:00", "05:30", purpose="CHARGING_ACCESS", pay=pay,
                                     sequence_number=None) | {"sequence_number": {"PAYABLE": 1, "NON_PAYABLE": 2, "TO_BE_CONFIRMED": 3}[pay]})
        assert r.status_code == 201
        assert r.json()["movement"]["payability_status"] == pay and r.json()["movement"]["movement_purpose"] == "CHARGING_ACCESS"
    bad = movement(world, "DEP", "CHG", "05:00", "05:30", pay="MAYBE")
    assert add(world, vid, bad).status_code == 422


def test_trip_validation_rules(world):
    s, vid = make_schedule(world)
    # wrong direction for the route's terminals: origin/destination swapped
    body = trip_body(world, "up", "T1", "06:00", "06:20", "06:22", "06:50")
    body["origin_location_id"], body["destination_location_id"] = body["destination_location_id"], body["origin_location_id"]
    add(world, vid, body)
    res = validate(world, vid)
    assert "TERMINAL_MISMATCH" in codes(res, "ERROR")
    # distance outside tolerance
    s2, v2 = make_schedule(world, "S2", "bus2")
    add(world, v2, trip_body(world, "up", "T1", "06:00", "06:20", "06:22", "06:50", km=14))
    assert "DISTANCE_MISMATCH" in codes(validate(world, v2), "ERROR")
    # stop from the other direction is rejected at the API
    s3, v3 = make_schedule(world, "S3", "bus2", effective_from="2027-01-01")
    body = trip_body(world, "up", "T1", "06:00", "06:20", "06:22", "06:50")
    body["trip"]["stops"][1]["route_stop_id"] = world["down"]["stops"][1]["route_stop_id"]
    assert add(world, v3, body).status_code == 422


def test_missing_stop_times_and_chronology(world):
    s, vid = make_schedule(world)
    body = trip_body(world, "up", "T1", "06:00", "06:20", "06:22", "06:50")
    body["trip"]["stops"][1]["scheduled_departure_time"] = None
    body["trip"]["stops"][1]["departure_day_offset"] = None
    add(world, vid, body)
    assert "STOP_TIME_MISSING" in codes(validate(world, vid), "ERROR")
    s2, v2 = make_schedule(world, "S2", "bus2")
    body = trip_body(world, "up", "T1", "06:00", "06:40", "06:20", "06:50")     # departs mid stop before arriving
    add(world, v2, body)
    assert {"STOP_DWELL"} & codes(validate(world, v2), "ERROR")


def test_soc_rules_and_no_odometer(world):
    s, vid = make_schedule(world)
    body = trip_body(world, "up", "T1", "06:00", "06:20", "06:22", "06:50")
    body["trip"]["planned_start_odometer_km"] = 500                         # odometer is not part of a schedule: ignored
    body["trip"]["stops"][0]["planned_odometer_km"] = 500
    r = add(world, vid, body)
    assert r.status_code == 201 and "planned_start_odometer_km" not in r.json()["trip"]
    body["trip"]["stops"][0]["planned_soc_pct"] = 120
    r = add(world, vid, {**body, "sequence_number": 9})
    assert r.status_code == 422                                              # SOC > 100 rejected by schema
    # SOC may rise while driving (regen) - not an error
    s2, v2 = make_schedule(world, "S2", "bus2")
    body = trip_body(world, "up", "T1", "06:00", "06:20", "06:22", "06:50")
    for st, soc in zip(body["trip"]["stops"], (80, 82, 78)):
        st["planned_soc_pct"] = soc
    add(world, v2, body)
    assert "SOC_RANGE" not in codes(validate(world, v2))


def test_optional_readings_can_be_made_mandatory(world):
    c, h = world["client"], world["h"]
    s, vid = make_schedule(world)
    add(world, vid, trip_body(world, "up", "T1", "06:00", "06:20", "06:22", "06:50"))
    assert "SOC_REQUIRED" not in codes(validate(world, vid))
    assert c.put("/api/settings", json={"values": {"require_stop_soc": True}}, headers=h).status_code == 200
    assert "SOC_REQUIRED" in codes(validate(world, vid), "ERROR")


def test_steering_time_counts_trips_and_movements(world):
    s, vid = make_schedule(world)
    build_good(world, vid)       # movements 40m + 40m, trips 50m + 55m, layover 20m (not driving)
    assert validate(world, vid)["summary"]["steering_minutes"] == 185


def test_versioning_creates_new_version_and_preserves_old(world):
    c, h = world["client"], world["h"]
    s, vid = make_schedule(world)
    build_good(world, vid)
    assert c.post(f"/api/schedule-versions/{vid}/publish", json={}, headers=h).status_code == 200
    sid = s["schedule_id"]
    r = c.post(f"/api/schedules/{sid}/versions", json={"valid_from": "2026-12-01", "change_reason": "retime"}, headers=h)
    assert r.status_code == 201
    v2 = r.json()
    assert v2["version_number"] == 2 and len(v2["activities"]) == 5      # copied from v1
    # only one draft at a time
    assert c.post(f"/api/schedules/{sid}/versions", json={"valid_from": "2027-01-01"}, headers=h).status_code == 409
    # edit v2 only
    first = v2["activities"][0]
    body = {"activity_type": first["activity_type"], "origin_location_id": first["origin_location_id"],
            "destination_location_id": first["destination_location_id"], "scheduled_start_time": "04:50",
            "scheduled_end_time": "05:40", "movement": {k: first["movement"][k] for k in
                                                         ("movement_purpose", "planned_distance_km", "payability_status", "payment_basis")}}
    assert c.put(f"/api/activities/{first['activity_id']}", json=body, headers=h).status_code == 200
    assert c.post(f"/api/schedule-versions/{v2['schedule_version_id']}/publish", json={"change_reason": "retime"}, headers=h).status_code == 200
    v1 = c.get(f"/api/schedule-versions/{vid}", headers=h).json()
    assert v1["status"] == "SUPERSEDED" and v1["valid_to"] == "2026-11-30"
    assert v1["activities"][0]["scheduled_start_time"] == "05:00"          # original plan intact
    # the right version applies on each date
    tl = lambda d: c.get(f"/api/schedules/{sid}/timeline?date={d}", headers=h).json()
    assert tl("2026-11-15")["version_number"] == 1 and tl("2026-12-15")["version_number"] == 2
    assert tl("2026-11-15")["activities"][0]["start_time"] == "05:00"
    assert tl("2026-12-15")["activities"][0]["start_time"] == "04:50"
    assert c.get(f"/api/schedules/{sid}/timeline?date=2026-10-01", headers=h).status_code == 404


def test_new_version_cannot_start_before_existing_published(world):
    c, h = world["client"], world["h"]
    s, vid = make_schedule(world)
    build_good(world, vid)
    c.post(f"/api/schedule-versions/{vid}/publish", json={}, headers=h)
    r = c.post(f"/api/schedules/{s['schedule_id']}/versions", json={"valid_from": "2026-11-01"}, headers=h)
    v2 = r.json()["schedule_version_id"]
    res = validate(world, v2)
    assert "VERSION_DATE_CONFLICT" in codes(res, "ERROR")
    assert c.post(f"/api/schedule-versions/{v2}/publish", json={"acknowledge_warnings": True}, headers=h).status_code == 422


def test_bus_conflict_between_schedules(world):
    c, h = world["client"], world["h"]
    s1, v1 = make_schedule(world, "S1", effective_to="2026-12-31")
    add(world, v1, layover(world, "DEP", "06:00", "10:00"))
    assert c.post(f"/api/schedule-versions/{v1}/publish", json={"acknowledge_warnings": True}, headers=h).status_code == 200
    s2, v2 = make_schedule(world, "S2")                         # same bus, same dates
    add(world, v2, layover(world, "DEP", "09:00", "12:00"))
    res = validate(world, v2)
    assert "BUS_CONFLICT" in codes(res, "ERROR")
    # non-overlapping hours are fine
    s3, v3 = make_schedule(world, "S3")
    add(world, v3, layover(world, "DEP", "10:00", "12:00"))
    assert "BUS_CONFLICT" not in codes(validate(world, v3))
    # same hours, different bus: fine
    s4, v4 = make_schedule(world, "S4", "bus2")
    add(world, v4, layover(world, "DEP", "09:00", "12:00"))
    assert "BUS_CONFLICT" not in codes(validate(world, v4))
    # same hours, disjoint dates: fine (S1 ends 2026-12-31)
    s5, v5 = make_schedule(world, "S5", effective_from="2030-01-01")
    add(world, v5, layover(world, "DEP", "09:00", "12:00"))
    assert "BUS_CONFLICT" not in codes(validate(world, v5))
    # same hours, dates overlapping S1's last day: conflict
    s6, v6 = make_schedule(world, "S6", effective_from="2026-12-31")
    add(world, v6, layover(world, "DEP", "09:00", "12:00"))
    assert "BUS_CONFLICT" in codes(validate(world, v6), "ERROR")
    # previous-evening cycle that runs past midnight into S1's morning: conflict (shifted occurrence)
    s7, v7 = make_schedule(world, "S7", effective_from="2026-12-30", effective_to="2026-12-30")
    add(world, v7, layover(world, "DEP", "20:00", "07:00", eo=1))
    assert "BUS_CONFLICT" in codes(validate(world, v7), "ERROR")


def test_multi_day_cycle_overlapping_next_day_is_rejected(world):
    c, h = world["client"], world["h"]
    s, vid = make_schedule(world)
    # 05:00 day0 -> 06:00 day1 = 25h: runs into the next daily occurrence
    add(world, vid, layover(world, "DEP", "05:00", "06:00", eo=1))
    res = validate(world, vid)
    assert "SELF_OVERLAP" in codes(res, "ERROR")
    # 05:00 -> 04:30 next day (23.5h) is fine and spans two calendar days
    s2, v2 = make_schedule(world, "S2", "bus2")
    add(world, v2, layover(world, "DEP", "05:00", "04:30", eo=1))
    res = validate(world, v2)
    assert "SELF_OVERLAP" not in codes(res) and res["summary"]["spans_days"] == 2
    # a 3-day cycle assigned to a bus conflicts with the next days' cycles
    s3, v3 = make_schedule(world, "S3", "bus2", effective_from="2026-11-01")
    add(world, v3, layover(world, "DEP", "08:00", "08:00", eo=2))
    assert "SELF_OVERLAP" in codes(validate(world, v3), "ERROR")


def test_sequence_uniqueness_reorder_and_trip_number(world):
    c, h = world["client"], world["h"]
    s, vid = make_schedule(world)
    assert add(world, vid, layover(world, "DEP", "05:00", "06:00") | {"sequence_number": 1}).status_code == 201
    assert add(world, vid, layover(world, "DEP", "06:00", "07:00") | {"sequence_number": 1}).status_code == 409
    a2 = add(world, vid, layover(world, "DEP", "06:00", "07:00")).json()
    ids = [x["activity_id"] for x in c.get(f"/api/schedule-versions/{vid}", headers=h).json()["activities"]]
    r = c.post(f"/api/schedule-versions/{vid}/activities/reorder", json={"activity_ids": ids[::-1]}, headers=h)
    assert r.status_code == 200 and [a["activity_id"] for a in r.json()["activities"]] == ids[::-1]
    assert c.post(f"/api/schedule-versions/{vid}/activities/reorder", json={"activity_ids": ids[:1]}, headers=h).status_code == 422
    # duplicate trip number
    assert add(world, vid, trip_body(world, "up", "T1", "08:00", "08:20", "08:22", "08:50")).status_code == 201
    assert add(world, vid, trip_body(world, "up", "T1", "09:00", "09:20", "09:22", "09:50")).status_code == 409


def test_inactive_vehicle_and_roles_on_publish(world, client):
    from .conftest import login
    s, vid = make_schedule(world)
    build_good(world, vid)
    sched = login(client, "scheduler", "Scheduler@123")
    assert client.post(f"/api/schedule-versions/{vid}/publish", json={}, headers=sched).status_code == 403
    assert client.post(f"/api/schedule-versions/{vid}/validate", headers=sched).status_code == 200
    r = client.put(f"/api/vehicles/{world['bus']['vehicle_id']}", headers=world["h"],
                   json={"fleet_number": "B1", "registration_number": "R-B1", "status": "INACTIVE"})
    assert r.status_code == 200
    assert "VEHICLE_INACTIVE" in codes(validate(world, vid), "ERROR")


def test_viewer_filters_and_print(world):
    c, h = world["client"], world["h"]
    s, vid = make_schedule(world)
    build_good(world, vid)
    c.post(f"/api/schedule-versions/{vid}/publish", json={}, headers=h)
    assert len(c.get("/api/schedules?on_date=2026-11-10", headers=h).json()) == 1
    assert len(c.get("/api/schedules?on_date=2026-10-10", headers=h).json()) == 0
    assert len(c.get("/api/schedules?activity_type=CHARGING", headers=h).json()) == 0
    assert len(c.get(f"/api/schedules?vehicle_id={world['bus']['vehicle_id']}&status=PUBLISHED", headers=h).json()) == 1
    p = c.get(f"/api/schedule-versions/{vid}/print?date=2026-11-10", headers=h).json()
    assert p["operating_date"] == "2026-11-10" and len(p["activities"]) == 5
    veh = c.get(f"/api/vehicles/{world['bus']['vehicle_id']}", headers=h).json()
    assert veh["assigned_schedules"] == ["S1"]


def test_unpublish_reopens_draft_and_restores_previous_version(world):
    c, h = world["client"], world["h"]
    s, vid = make_schedule(world)
    build_good(world, vid)
    sid = s["schedule_id"]
    assert c.post(f"/api/schedule-versions/{vid}/publish", json={}, headers=h).status_code == 200
    v2 = c.post(f"/api/schedules/{sid}/versions", json={"valid_from": "2026-12-01"}, headers=h).json()["schedule_version_id"]
    assert c.post(f"/api/schedule-versions/{v2}/publish", json={}, headers=h).status_code == 200
    # only the live version, and only by a publisher
    assert c.post(f"/api/schedule-versions/{vid}/unpublish", headers=h).status_code == 409
    from .conftest import login
    cc = int(h["X-Cost-Center-Id"])
    assert c.post("/api/users", json={"username": "sch", "password": "Sch@12345", "full_name": "S",
                                      "cost_center_roles": [{"cost_center_id": cc, "role": "SCHEDULER"}]}, headers=h).status_code == 201
    assert c.post(f"/api/schedule-versions/{v2}/unpublish", headers=login(c, "sch", "Sch@12345")).status_code == 403
    r = c.post(f"/api/schedule-versions/{v2}/unpublish", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "DRAFT"
    v1 = c.get(f"/api/schedule-versions/{vid}", headers=h).json()
    assert v1["status"] == "PUBLISHED" and v1["valid_to"] is None
    # the reopened draft is editable again
    assert add(world, v2, layover(world, "TA", "09:00", "09:30")).status_code == 201
    # unpublishing the last live version makes the whole schedule a draft (and then deletable)
    assert c.delete(f"/api/schedule-versions/{v2}", headers=h).status_code == 204
    assert c.post(f"/api/schedule-versions/{vid}/unpublish", headers=h).status_code == 200
    assert c.get(f"/api/schedules/{sid}", headers=h).json()["status"] == "DRAFT"


def test_only_never_published_schedules_can_be_deleted(world):
    c, h = world["client"], world["h"]
    s, vid = make_schedule(world)
    build_good(world, vid)
    s2, vid2 = make_schedule(world, code="S2", bus_key="bus2")
    build_good(world, vid2)
    assert c.post(f"/api/schedule-versions/{vid}/publish", json={}, headers=h).status_code == 200
    assert c.delete(f"/api/schedules/{s['schedule_id']}", headers=h).status_code == 409
    assert c.delete(f"/api/schedules/{s2['schedule_id']}", headers=h).status_code == 204
    assert c.get(f"/api/schedules/{s2['schedule_id']}", headers=h).status_code == 404


def test_layover_soc_can_drop_but_not_rise(world):
    s, vid = make_schedule(world)
    body = layover(world, "TA", "09:00", "09:40")
    body["layover"].update(planned_start_soc_pct=70, planned_end_soc_pct=66)      # A/C running
    r = add(world, vid, body)
    assert r.status_code == 201 and float(r.json()["layover"]["planned_end_soc_pct"]) == 66
    assert "LAYOVER_SOC_RISE" not in codes(validate(world, vid))
    body = layover(world, "TA", "09:40", "10:00")
    body["layover"].update(planned_start_soc_pct=66, planned_end_soc_pct=80)
    add(world, vid, body)
    assert "LAYOVER_SOC_RISE" in codes(validate(world, vid), "WARNING")


def test_non_revenue_km_split_by_payability(world):
    s, vid = make_schedule(world)
    assert add(world, vid, movement(world, "DEP", "TA", "05:00", "05:40", km=5, pay="PAYABLE")).status_code == 201
    assert add(world, vid, movement(world, "TA", "DEP", "06:00", "06:40", km=3, pay="NON_PAYABLE")).status_code == 201
    summ = validate(world, vid)["summary"]
    assert summ["non_revenue_km"] == 8
    assert summ["non_revenue_km_by_payability"] == {"PAYABLE": 5, "NON_PAYABLE": 3, "TO_BE_CONFIRMED": 0}
    assert add(world, vid, trip_body(world, "up", "T1", "07:00", "07:20", "07:22", "07:50")).status_code == 201
    assert validate(world, vid)["summary"]["billable_km"] == 10 + 5           # trip km + payable movement km



def halt(w, loc, start, end, so=0, eo=0, ss=None, es=None):
    return {"activity_type": "HALT", "origin_location_id": w["loc"][loc], "destination_location_id": w["loc"][loc],
            "start_day_offset": so, "scheduled_start_time": start, "end_day_offset": eo, "scheduled_end_time": end,
            "halt": {"location_id": w["loc"][loc], "planned_start_soc_pct": ss, "planned_end_soc_pct": es}}


def test_depot_halt_is_one_block_outside_cycle_time(world):
    c, h = world["client"], world["h"]
    s, vid = make_schedule(world)
    build_good(world, vid)                                           # 05:00 -> 08:45 at the depot
    r = add(world, vid, halt(world, "DEP", "08:45", "05:00", eo=1, ss=30, es=95))   # charged inside the halt
    assert r.status_code == 201, r.text
    res = validate(world, vid)
    assert res["valid"], res["issues"]                               # exactly 24h, SOC rise is fine
    summ = res["summary"]
    assert summ["cycle_minutes"] == 24 * 60                          # full span still guards bus conflicts
    assert summ["operating_minutes"] == 3 * 60 + 45 and summ["operating_spans_days"] == 1
    assert summ["halt_minutes"] == 20 * 60 + 15
    assert c.get(f"/api/schedule-versions/{vid}/timeline", headers=h).json()["activities"][-1]["halt"]["end_soc"] == 95


def test_night_halt_at_terminal_and_mid_day_halt(world):
    s, vid = make_schedule(world)
    assert add(world, vid, halt(world, "TA", "04:30", "06:00")).status_code == 201       # morning night-halt
    assert add(world, vid, trip_body(world, "up", "T1", "06:00", "06:20", "06:22", "06:50")).status_code == 201
    assert add(world, vid, halt(world, "TB", "06:50", "16:00")).status_code == 201       # peak-only bus, mid-day halt
    assert add(world, vid, trip_body(world, "down", "T2", "16:00", "16:20", "16:22", "16:55")).status_code == 201
    summ = validate(world, vid)["summary"]
    assert summ["operating_start_min"] == 360 and summ["operating_minutes"] == 50 + 55
    assert summ["halt_minutes"] == 90 + 550
    bad = halt(world, "TA", "17:00", "18:00")
    bad["destination_location_id"] = world["loc"]["TB"]
    add(world, vid, bad)
    assert "HALT_LOCATION" in codes(validate(world, vid), "ERROR")


def test_effective_from_can_be_changed_within_the_rules(world):
    c, h = world["client"], world["h"]
    s, vid = make_schedule(world)                                    # effective and v1 from 2026-11-01, draft
    build_good(world, vid)
    put = lambda body: c.put(f"/api/schedules/{s['schedule_id']}", json=body, headers=h)
    # draft: the first version moves with the schedule, both later and earlier
    assert put({"effective_from": "2026-11-10"}).status_code == 200
    assert c.get(f"/api/schedule-versions/{vid}", headers=h).json()["valid_from"] == "2026-11-10"
    assert put({"effective_from": "2026-11-05"}).json()["effective_from"] == "2026-11-05"
    assert c.get(f"/api/schedule-versions/{vid}", headers=h).json()["valid_from"] == "2026-11-05"
    assert put({"effective_from": "2026-12-01", "effective_to": "2026-11-20"}).status_code == 422
    # published: a later start would cut off v1; an earlier start is fine and v1 keeps its date
    assert c.post(f"/api/schedule-versions/{vid}/publish", json={}, headers=h).status_code == 200
    r = put({"effective_from": "2026-11-06"})
    assert r.status_code == 409 and "v1" in r.text
    assert put({"effective_from": "2026-11-01"}).status_code == 200
    assert c.get(f"/api/schedule-versions/{vid}", headers=h).json()["valid_from"] == "2026-11-05"
    # a trip sheet pins the start
    assert c.post("/api/trip-sheets", json={"schedule_id": s["schedule_id"], "operating_date": "2026-11-05"}, headers=h).status_code == 201
    r = put({"effective_from": "2026-11-07"})
    assert r.status_code == 409


def test_fill_in_layovers(world):
    c, h = world["client"], world["h"]
    s, vid = make_schedule(world)
    # movement into TA ending 05:40 at SOC 90, trip T1 from TA at 06:00 starting at SOC 88: a 20 min idle gap at TA
    m = movement(world, "DEP", "TA", "05:00", "05:40")
    m["movement"]["planned_end_soc_pct"] = 90
    assert add(world, vid, m).status_code == 201
    t1 = trip_body(world, "up", "T1", "06:00", "06:20", "06:22", "06:50")
    t1["trip"]["planned_start_soc_pct"] = 88
    assert add(world, vid, t1).status_code == 201
    # a layover at TB with stale times, then T2 from TB at 07:10
    assert add(world, vid, layover(world, "TB", "06:55", "07:00")).status_code == 201
    assert add(world, vid, trip_body(world, "down", "T2", "07:10", "07:30", "07:32", "08:05")).status_code == 201
    # a gap that changes location (T2 ends at TA, next movement leaves DEP) is only reported
    assert add(world, vid, movement(world, "DEP", "TA", "09:00", "09:30", purpose="RETURN_TO_SERVICE")).status_code == 201
    r = c.post(f"/api/schedule-versions/{vid}/fill-layovers", headers=h)
    assert r.status_code == 200, r.text
    res, v = r.json()["result"], r.json()["version"]
    assert res["created"] == 1 and res["updated"] == 1 and len(res["skipped"]) == 1
    acts = v["activities"]
    assert [a["activity_type"] for a in acts] == ["NON_REVENUE_MOVEMENT", "LAYOVER", "PASSENGER_TRIP", "LAYOVER",
                                                  "PASSENGER_TRIP", "NON_REVENUE_MOVEMENT"]
    gap = acts[1]
    assert (gap["scheduled_start_time"], gap["scheduled_end_time"], gap["origin_code"]) == ("05:40", "06:00", "TA")
    assert float(gap["layover"]["planned_start_soc_pct"]) == 90 and float(gap["layover"]["planned_end_soc_pct"]) == 88
    assert gap["layover"]["layover_purpose"] == "TERMINAL_RECOVERY"
    snapped = acts[3]
    assert (snapped["scheduled_start_time"], snapped["scheduled_end_time"]) == ("06:50", "07:10")
    assert [a["sequence_number"] for a in acts] == [1, 2, 3, 4, 5, 6]
    # running it again changes nothing
    assert c.post(f"/api/schedule-versions/{vid}/fill-layovers", headers=h).json()["result"]["created"] == 0


def test_fill_in_carries_soc_into_charging(world):
    c, h = world["client"], world["h"]
    s, vid = make_schedule(world)
    m = movement(world, "TA", "CHG", "08:05", "08:30", purpose="CHARGING_ACCESS")
    m["movement"]["planned_end_soc_pct"] = 35
    assert add(world, vid, m).status_code == 201
    ch = charging(world, "CHG", "08:30", "10:30")                        # entered as 20 -> 90
    assert add(world, vid, ch).status_code == 201
    back = movement(world, "CHG", "TA", "10:30", "10:55", purpose="RETURN_TO_SERVICE")
    back["movement"]["planned_start_soc_pct"] = 92
    assert add(world, vid, back).status_code == 201
    r = c.post(f"/api/schedule-versions/{vid}/fill-layovers", headers=h).json()
    assert r["result"]["charging_updated"] == 1 and r["result"]["created"] == 0
    chg = next(a for a in r["version"]["activities"] if a["activity_type"] == "CHARGING")
    assert float(chg["charging"]["planned_start_soc_pct"]) == 35 and float(chg["charging"]["planned_end_soc_pct"]) == 92
    assert (chg["scheduled_start_time"], chg["scheduled_end_time"]) == ("08:30", "10:30")   # times untouched


def test_fill_in_carries_soc_into_a_halt(world):
    c, h = world["client"], world["h"]
    s, vid = make_schedule(world)
    m = movement(world, "TA", "DEP", "20:00", "20:30", purpose="RETURN_TO_DEPOT")
    m["movement"]["planned_end_soc_pct"] = 25
    assert add(world, vid, m).status_code == 201
    halt = {"activity_type": "HALT", "origin_location_id": world["loc"]["DEP"], "destination_location_id": world["loc"]["DEP"],
            "scheduled_start_time": "20:30", "end_day_offset": 1, "scheduled_end_time": "05:00",
            "halt": {"location_id": world["loc"]["DEP"]}}
    assert add(world, vid, halt).status_code == 201
    nxt = movement(world, "DEP", "TA", "05:00", "05:30", start_day_offset=1, end_day_offset=1)
    nxt["movement"]["planned_start_soc_pct"] = 98                        # charged overnight inside the halt
    assert add(world, vid, nxt).status_code == 201
    r = c.post(f"/api/schedule-versions/{vid}/fill-layovers", headers=h).json()
    assert r["result"]["halt_updated"] == 1
    hl = next(a for a in r["version"]["activities"] if a["activity_type"] == "HALT")
    assert float(hl["halt"]["planned_start_soc_pct"]) == 25 and float(hl["halt"]["planned_end_soc_pct"]) == 98
    assert (hl["scheduled_start_time"], hl["end_day_offset"], hl["scheduled_end_time"]) == ("20:30", 1, "05:00")


def test_clone_copies_a_schedule_onto_another_bus_as_a_draft(world, client):
    """A second bus running the same pattern is set up by copying, not by typing it all again."""
    from .conftest import make_schedule
    s, vid = make_schedule(world)
    build_good(world, vid)
    h = world["h"]
    assert client.post(f"/api/schedule-versions/{vid}/publish", json={}, headers=h).status_code == 200
    runs = len(client.get(f"/api/schedule-versions/{vid}", headers=h).json()["activities"])

    body = {"schedule_code": "S1-COPY", "schedule_name": "Copy of S1", "vehicle_id": world["bus2"]["vehicle_id"],
            "effective_from": "2026-11-01"}
    r = client.post(f"/api/schedules/{s['schedule_id']}/clone", json=body, headers=h)
    assert r.status_code == 201
    copy = r.json()
    # a draft on the new bus, starting at version 1, with the source's runs
    assert copy["status"] == "DRAFT" and copy["fleet_number"] == "B2"
    assert [v["version_number"] for v in copy["versions"]] == [1]
    assert copy["versions"][0]["status"] == "DRAFT"
    new_vid = copy["versions"][0]["schedule_version_id"]
    detail = client.get(f"/api/schedule-versions/{new_vid}", headers=h).json()
    assert len(detail["activities"]) == runs
    assert detail["change_reason"] == f"Cloned from {s['schedule_code']} v1"
    # the source is untouched, and the copy is its own schedule
    assert client.get(f"/api/schedules/{s['schedule_id']}", headers=h).json()["versions"][0]["status"] == "PUBLISHED"
    # the same code twice is refused, and a bus of another cost center is not accepted
    assert client.post(f"/api/schedules/{s['schedule_id']}/clone", json=body, headers=h).status_code == 409
    assert client.post(f"/api/schedules/{s['schedule_id']}/clone", headers=h,
                       json={**body, "schedule_code": "S1-X", "vehicle_id": 9999}).status_code == 422
    # and the copy publishes on its own, like any draft
    assert client.post(f"/api/schedule-versions/{new_vid}/publish", json={}, headers=h).status_code == 200
