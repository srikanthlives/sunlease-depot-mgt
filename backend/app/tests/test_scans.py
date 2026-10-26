"""Uploading scanned paper sheets: what happens around the reading.

The reading itself (finding the boxes on a page and making out the characters) is checked against
real printed sheets with the harness in the scratchpad, because it needs tesseract and a scanner-like
PDF. What is checked here is everything the depot depends on regardless of how well a page reads:
who may upload, that a new upload replaces the old one, that a locked sheet is never touched, and
that the layover/SOC fill runs on what was read.
"""
import datetime as dt
import io

import pytest

from app.models.models import SheetScan, SheetScanPage, TripSheet
from app.services import scan_intake
from app.services import trip_sheet_service as ts

from .conftest import login
from .test_trip_sheets import as_planned, driver_on, new_sheet, published, save, staff

DATE = "2026-11-05"


def published_second(world):
    """A second published schedule, on its own bus."""
    from .conftest import make_schedule
    from .test_schedules import build_good
    s, vid = make_schedule(world, code="S2", bus_key="bus2")
    build_good(world, vid)
    assert world["client"].post(f"/api/schedule-versions/{vid}/publish", json={}, headers=world["h"]).status_code == 200
    return s, vid


def upload(client, headers, content=b"%PDF-1.4 not really a pdf", name="scan.pdf", date=DATE, **extra):
    data = {"operating_date": date, **extra}
    return client.post("/api/trip-sheets/scans", files={"files": (name, io.BytesIO(content), "application/pdf")},
                       data=data, headers=headers)


def test_only_a_clerk_may_upload_and_only_a_pdf(world, client):
    published(world)
    h = world["h"]
    assert upload(client, h, name="sheet.jpg").status_code == 422          # photographs are not accepted
    viewer = login(client, "viewer", "Viewer@123")
    assert upload(client, viewer).status_code == 403
    # a PDF that is not readable fails the whole scan, and says so rather than inventing data
    r = upload(client, h)
    assert r.status_code == 201
    body = r.json()[0]
    assert body["status"] == "FAILED" and body["message"]
    assert client.get("/api/trip-sheets/scans?operating_date=" + DATE, headers=h).json()[0]["status"] == "FAILED"


def test_several_files_upload_together_and_do_not_replace_each_other(world, client):
    """A depot scans a few buses to separate files; one batch is one upload, not a race."""
    published(world)
    h = world["h"]
    r = client.post("/api/trip-sheets/scans", headers=h, data={"operating_date": DATE}, files=[
        ("files", ("bus-a.pdf", io.BytesIO(b"%PDF-1.4 a"), "application/pdf")),
        ("files", ("bus-b.pdf", io.BytesIO(b"%PDF-1.4 b"), "application/pdf")),
    ])
    assert r.status_code == 201
    body = r.json()
    assert [x["file_name"] for x in body] == ["bus-a.pdf", "bus-b.pdf"]
    listed = client.get(f"/api/trip-sheets/scans?operating_date={DATE}", headers=h).json()
    assert len(listed) == 2 and all(x["status"] != "SUPERSEDED" for x in listed)
    # one file that is not a PDF stops the whole batch, before anything is read
    r = client.post("/api/trip-sheets/scans", headers=h, data={"operating_date": DATE}, files=[
        ("files", ("ok.pdf", io.BytesIO(b"%PDF-1.4 a"), "application/pdf")),
        ("files", ("photo.jpg", io.BytesIO(b"xx"), "image/jpeg")),
    ])
    assert r.status_code == 422 and "photo.jpg" in r.json()["detail"]
    assert len(client.get(f"/api/trip-sheets/scans?operating_date={DATE}", headers=h).json()) == 2


def test_a_page_for_another_bus_or_day_is_rejected(world, client, db):
    """The row's own upload button is scoped to one bus: another bus's paper must not be applied."""
    import datetime as dt

    from app.models.models import BusSchedule
    from app.services.scan_intake import rejection

    s, _ = published(world)
    other, _ = published_second(world)
    mine = db.get(BusSchedule, s["schedule_id"])
    theirs = db.get(BusSchedule, other["schedule_id"])
    day = dt.date.fromisoformat(DATE)
    scan = SheetScan(cost_center_id=1, operating_date=day, schedule_id=mine.schedule_id, file_name="row.pdf")

    # the page is the bus it was uploaded against, on the day it was uploaded for: it belongs
    assert rejection(scan, mine, day, mine) is None
    # another bus: rejected, and the message names both buses so a clerk knows where it belongs
    bad = rejection(scan, theirs, day, mine)
    assert bad["severity"] == "ERROR" and bad["code"] == "WRONG_SHEET"
    assert theirs.schedule_code in bad["message"] and mine.schedule_code in bad["message"]
    assert theirs.vehicle.fleet_number in bad["message"] and "nothing was changed" in bad["message"]
    # the right bus but another day: rejected too
    wrong_day = rejection(scan, mine, day + dt.timedelta(days=1), mine)
    assert wrong_day["code"] == "WRONG_DATE" and "nothing was changed" in wrong_day["message"]
    # a whole-day upload (no bus named) takes any bus of the cost center - that is the point of it
    whole_day = SheetScan(cost_center_id=1, operating_date=day, file_name="day.pdf")
    assert rejection(whole_day, theirs, day, None) is None


def test_a_new_upload_supersedes_the_one_before_it(world, client, db):
    published(world)
    h = world["h"]
    first = SheetScan(cost_center_id=1, operating_date=dt.date.fromisoformat(DATE), file_name="monday.pdf",
                      page_count=2, status="DONE")
    db.add(first)
    db.commit()
    second = SheetScan(cost_center_id=1, operating_date=dt.date.fromisoformat(DATE), file_name="monday-again.pdf",
                       page_count=2, status="DONE")
    db.add(second)
    db.flush()
    scan_intake.supersede(db, second)
    db.commit()
    db.refresh(first)
    assert first.status == "SUPERSEDED" and first.superseded_by == second.scan_id
    # the list leaves the replaced upload out unless it is asked for
    listed = client.get(f"/api/trip-sheets/scans?operating_date={DATE}", headers=h).json()
    assert [x["file_name"] for x in listed] == ["monday-again.pdf"]
    both = client.get(f"/api/trip-sheets/scans?operating_date={DATE}&include_superseded=true", headers=h).json()
    assert len(both) == 2


def test_fill_in_layovers_and_soc_runs_on_what_was_read(world, db):
    """A scan fills the runs; the layovers between them are filled the same way the button does it."""
    s, _ = published(world)
    sheet = new_sheet(world, s, DATE)
    save(world, sheet, as_planned(sheet), driver_on(sheet, staff(world, "D1")))
    row = db.query(TripSheet).filter(TripSheet.sheet_id == sheet["sheet_id"]).one()
    layovers = [r for r in row.rows if r.activity and r.activity.activity_type == "LAYOVER"]
    assert layovers, "the test schedule should have a layover between the trips"
    for lay in layovers:                       # as a scan leaves them: nothing written on paper
        lay.actual_start_time = lay.actual_end_time = None
        lay.start_soc_pct = lay.end_soc_pct = None
    db.flush()
    filled = ts.fill_stationary(row)
    db.flush()
    assert filled["times"] + filled["socs"] > 0
    for lay in layovers:
        assert lay.actual_start_time is not None and lay.actual_end_time is not None
        assert lay.actual_start_time < lay.actual_end_time


def test_a_submitted_sheet_is_never_overwritten_by_a_scan(world, client, db):
    """Paper that arrives late must not quietly change a sheet somebody has already signed off."""
    s, _ = published(world)
    h = world["h"]
    sheet = new_sheet(world, s, DATE)
    save(world, sheet, as_planned(sheet), driver_on(sheet, staff(world, "D1")))
    assert client.post(f"/api/trip-sheets/{sheet['sheet_id']}/submit", headers=h).status_code == 200
    scan = SheetScan(cost_center_id=1, operating_date=dt.date.fromisoformat(DATE), file_name="late.pdf",
                     status="PROCESSING")
    db.add(scan)
    db.flush()
    page = SheetScanPage(scan_id=scan.scan_id, page_no=1)
    scan.pages.append(page)
    db.flush()
    row = db.query(TripSheet).filter(TripSheet.sheet_id == sheet["sheet_id"]).one()
    before = [(r.status, r.actual_start_time) for r in row.rows]
    # the page says it is this sheet, but the sheet is submitted: the page is skipped, not applied
    assert row.status == "SUBMITTED"
    page.sheet_id, page.status = row.sheet_id, "SKIPPED"
    db.flush()
    assert [(r.status, r.actual_start_time) for r in row.rows] == before


def test_the_sheet_carries_its_scanned_pages_and_the_fields_to_key_in(world, client, db):
    s, _ = published(world)
    h = world["h"]
    sheet = new_sheet(world, s, DATE)
    plain = client.get(f"/api/trip-sheets/{sheet['sheet_id']}/scan", headers=h).json()
    assert plain["from_scan"] is False and plain["pages"] == []   # keyed in by hand, no paper attached
    scan = SheetScan(cost_center_id=1, operating_date=dt.date.fromisoformat(DATE), file_name="x.pdf", status="DONE")
    db.add(scan)
    db.flush()
    page = SheetScanPage(
        scan_id=scan.scan_id, page_no=1, sheet_id=sheet["sheet_id"], status="WARNED", fields_read=120, fields_unsure=2,
        issues='[{"severity":"WARNING","code":"FIELD_UNSURE","message":"Run 3: odo end could not be read",'
               '"run":"Run 3","field":"end_odometer_km"},'
               '{"severity":"WARNING","code":"ODO_GAP","message":"a gap in the odometer","run":null,"field":null}]')
    scan.pages.append(page)
    db.flush()
    row = db.query(TripSheet).filter(TripSheet.sheet_id == sheet["sheet_id"]).one()
    row.scanned_page_id = page.page_id
    db.commit()
    out = client.get(f"/api/trip-sheets/{sheet['sheet_id']}/scan", headers=h).json()
    assert out["from_scan"] and out["fields_unsure"] == 2
    # the page itself is attached to the sheet, so the clerk can read the paper beside the entry
    assert [p["page_no"] for p in out["pages"]] == [1]
    assert out["pages"][0]["image_url"].endswith(f"/scans/{scan.scan_id}/pages/1/image")
    assert out["file_name"] == "x.pdf"
    # only what the paper could not tell us: the validation finding is shown by the validate panel
    assert [x["code"] for x in out["issues"]] == ["FIELD_UNSURE"]
    assert out["issues"][0]["field"] == "end_odometer_km"


def test_the_board_carries_the_warning_and_error_counts(world, client):
    """The daily board shows a symbol per bus, so a clerk can see which sheets need attention."""
    s, _ = published(world)
    h = world["h"]
    sheet = new_sheet(world, s, DATE)
    # times that cannot be right: the sheet saves, but validation records errors against it
    rows = as_planned(sheet, T1={"actual_start_time": "09:00", "actual_end_time": "06:00"})
    save(world, sheet, rows, driver_on(sheet, staff(world, "D1")))
    row = next(r for r in client.get(f"/api/trip-sheets/board?date={DATE}", headers=h).json()
               if r["sheet_id"] == sheet["sheet_id"])
    assert row["validation_errors"] + row["validation_warnings"] > 0
    assert row["from_scan"] is False


# --------------------------------------------------------------------------
# The reader itself, when tesseract is installed (it is, in the Docker image)
# --------------------------------------------------------------------------
scan_service = pytest.importorskip("app.services.scan_service")
needs_tesseract = pytest.mark.skipif(not scan_service.tesseract_available(),
                                     reason="tesseract is not installed on this machine")


def test_field_layout_follows_what_the_run_is():
    """The boxes printed for a run depend on the run, so the reader is told rather than guessing."""
    trip = scan_service.fields_for(is_trip=True, is_charging=False)
    assert sum(c for _, c in trip) == 35                       # 3 ticks + times + odometers + SOC + reason + stop
    movement = scan_service.fields_for(is_trip=False, is_charging=False)
    assert sum(c for _, c in movement) == 32                   # no "Cut" tick, no stop box
    charging = scan_service.fields_for(is_trip=False, is_charging=True)
    assert sum(c for _, c in charging) == 20                   # and no odometer boxes
    assert [n for n, _ in charging] == ["status", "departed", "arrived", "arrived_day", "start_soc", "end_soc", "reason"]


@needs_tesseract
def test_a_blank_field_is_not_reported_as_unreadable():
    """Most boxes on a real sheet are empty; only ink that cannot be made out is worth a warning."""
    import numpy as np
    blank = np.full((60, 200), 255, np.uint8)
    cells = [scan_service.Cell(10 + i * 40, 10, 33, 43) for i in range(3)]
    text, conf = scan_service.read_digits(blank, cells)
    assert text == "" and conf == 100.0
    assert scan_service.written(blank, cells) == [False, False, False]
