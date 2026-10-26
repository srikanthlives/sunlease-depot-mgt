"""Turning a scanned PDF into draft trip sheets.

scan_service does the image work and knows nothing about the database; this module decides what the
readings mean: which sheet a page belongs to, which run each box row is, and what to do when a
reading cannot be trusted. A scan never submits or approves anything - it fills drafts, runs the
layover/SOC fill and then validation, and leaves every doubt as an issue naming the one field to
correct on the trip sheet screen.

A new upload for the same cost center and date supersedes the earlier one: the drafts it covers are
re-read from the new pages, so re-scanning a batch is the normal way to correct a bad scan.
"""
from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.enums import ActivityType, RowStatus, TripSheetStatus
from app.models.models import (
    BusSchedule, SheetScan, SheetScanPage, TripReason, TripSheet, TripSheetRow,
)
from app.services import scan_service as sc
from app.services import trip_sheet_service as ts

# layovers and halts print as reference lines without boxes, so they are not in the scanned sequence
REFERENCE_ONLY = (ActivityType.LAYOVER, ActivityType.HALT)
BOXED = tuple(t for t in ActivityType.ALL if t not in REFERENCE_ONLY)


def _issue(sev, code, msg, run=None, field=None):
    return {"severity": sev, "code": code, "message": msg, "run": run, "field": field}


def rejection(scan: SheetScan, found: BusSchedule, on: dt.date, want: BusSchedule | None) -> dict | None:
    """Why a page does not belong to the upload it arrived in, or None when it does.

    An upload made from one bus's row carries that schedule: a page for another bus, or another day,
    is rejected outright rather than applied, so paper dropped on the wrong row cannot overwrite a
    sheet that has nothing to do with it. A whole-day upload (no schedule) accepts any bus of the
    cost center, which is the point of it.
    """
    if want is not None and found.schedule_id != want.schedule_id:
        return _issue("ERROR", "WRONG_SHEET",
                      f"this page is {found.vehicle.fleet_number} ({found.schedule_code}), but it was uploaded "
                      f"against {want.vehicle.fleet_number} ({want.schedule_code}) - nothing was changed. Upload it "
                      f"on that bus's row, or use Upload scanned sheets for the whole day")
    if want is not None and scan.operating_date and on != scan.operating_date:
        return _issue("ERROR", "WRONG_DATE",
                      f"this page is for {on.isoformat()}, but it was uploaded against "
                      f"{scan.operating_date.isoformat()} - nothing was changed. Open that date and upload it there")
    return None


def process(db: Session, scan: SheetScan, pdf_bytes: bytes, user) -> SheetScan:
    """Read every page of the upload and write what it says onto draft sheets."""
    if not sc.tesseract_available():
        scan.status, scan.message = "FAILED", ("Scanned-sheet reading is not installed on this server "
                                               "(tesseract missing) - enter the sheets by hand")
        db.flush()
        return scan
    try:
        pages = sc.rasterise(pdf_bytes)
    except ValueError as e:
        scan.status, scan.message = "FAILED", str(e)
        db.flush()
        return scan
    scan.page_count = len(pages)
    if not pages:
        scan.status, scan.message = "FAILED", "the PDF has no pages"
        db.flush()
        return scan

    # page order matters: a long day runs over several pages of the same sheet, and the second page
    # carries on where the first stopped
    seen: dict[int, int] = {}            # sheet_id -> how many box rows already taken from earlier pages
    touched: dict[int, TripSheet] = {}
    for i, raw in enumerate(pages, start=1):
        page = SheetScanPage(scan_id=scan.scan_id, page_no=i)
        scan.pages.append(page)
        db.flush()                       # the page needs its id before a sheet can point at it
        try:
            _read_page(db, scan, page, raw, seen, touched, user)
        except Exception as e:                               # noqa: BLE001 - one bad page must not lose the rest
            page.status = "UNREADABLE"
            page.issues = json.dumps([_issue("ERROR", "PAGE_FAILED", f"page {i} could not be processed: {e}")])
    # the sheets this scan filled: carry the actuals through the layovers, then validate
    for sheet in touched.values():
        ts.fill_stationary(sheet)
    db.flush()
    for sheet in touched.values():
        result = ts.validate_sheet(db, sheet)
        for page in scan.pages:
            if page.sheet_id == sheet.sheet_id:
                page.issues = json.dumps(json.loads(page.issues or "[]") + _validation_issues(result))
                if any(x["severity"] == "ERROR" for x in json.loads(page.issues)):
                    page.status = "WARNED" if page.status == "OK" else page.status
    scan.status = "DONE"
    if scan.schedule_id and not touched:
        rejected = [p for p in scan.pages if p.status == "REJECTED"]
        scan.status = "FAILED"
        scan.message = (json.loads(rejected[0].issues)[0]["message"] if rejected
                        else "none of the pages in this file could be matched to this bus and day "
                             "- nothing was changed")
    db.flush()
    return scan


def _validation_issues(result: dict) -> list[dict]:
    """Validation errors and warnings, in the same shape as the reading issues."""
    out = []
    for sev in ("errors", "warnings"):
        for x in result.get(sev, []):
            out.append(_issue("ERROR" if sev == "errors" else "WARNING", x.get("code", ""),
                              x.get("message", ""), run=x.get("label")))
    return out


def _read_page(db: Session, scan: SheetScan, page: SheetScanPage, raw, seen, touched, user) -> None:
    img = sc.deskew(raw)
    page.image_path = sc.save_page(scan.scan_id, page.page_no, img)
    cells = sc.find_cells(img)
    ident = sc.read_id_line(img, cells)
    # the crew block also has boxes; only the rows below the ID line belong to runs
    rows = [r for r in sc.rows_of(cells) if min(c.y for c in r) > ident.y]
    issues: list[dict] = []

    if ident.schedule_id is None:
        page.status = "UNREADABLE"
        page.issues = json.dumps([_issue("ERROR", "NO_ID_LINE",
                                         "the printed ID line could not be read on this page, so it is not clear "
                                         "which bus and day it belongs to - rescan this page, or enter it by hand")])
        return
    page.schedule_id, page.version_number = ident.schedule_id, ident.version_number

    on = ident.date or sc.read_hand_date(img, cells) or scan.operating_date
    page.read_date = on
    if on is None:
        page.status = "UNREADABLE"
        page.issues = json.dumps([_issue("ERROR", "NO_DATE",
                                         "this page carries no printed date and the handwritten date boxes could "
                                         "not be read - write the date in the boxes and rescan, or enter it by hand")])
        return

    schedule = db.get(BusSchedule, ident.schedule_id)
    if schedule is None or schedule.cost_center_id != scan.cost_center_id:
        page.status = "SKIPPED"
        page.issues = json.dumps([_issue("ERROR", "WRONG_COST_CENTER",
                                         f"schedule {ident.schedule_id} on this page does not belong to this cost "
                                         f"center - upload it in the cost center that runs it")])
        return
    wrong = rejection(scan, schedule, on, db.get(BusSchedule, scan.schedule_id) if scan.schedule_id else None)
    if wrong:
        page.status = "REJECTED"
        page.issues = json.dumps([wrong])
        return

    sheet = db.query(TripSheet).filter(TripSheet.schedule_id == schedule.schedule_id,
                                       TripSheet.operating_date == on).first()
    if sheet is None:
        sheet = ts.create_sheet(db, schedule, on, user)
        db.flush()
    if sheet.status in (TripSheetStatus.SUBMITTED, TripSheetStatus.APPROVED):
        page.sheet_id = sheet.sheet_id
        page.status = "SKIPPED"
        page.issues = json.dumps([_issue("ERROR", "SHEET_LOCKED",
                                         f"the sheet for {schedule.schedule_code} on {on} is already "
                                         f"{sheet.status.lower()} - it was left untouched. Reopen it first if the "
                                         f"paper has changed")])
        return
    page.sheet_id = sheet.sheet_id

    if ident.version_number and sheet.version.version_number != ident.version_number:
        sheet.paper_version_number = ident.version_number     # the entry screen warns about the mismatch
        issues.append(_issue("WARNING", "PAPER_VERSION",
                             f"the paper was printed from v{ident.version_number} but v"
                             f"{sheet.version.version_number} applies on {on}", field="paper_version_number"))

    # the first page of a sheet starts a fresh read of that sheet
    start = seen.get(sheet.sheet_id)
    if start is None:
        start = 0
        _reset_rows(sheet)
    boxed = [r for r in sorted(sheet.rows, key=lambda r: r.row_sequence)
             if r.activity is not None and r.activity.activity_type in BOXED]
    mine = boxed[start:start + len(rows)]
    if len(rows) > len(mine):
        issues.append(_issue("WARNING", "EXTRA_ROWS",
                             f"{len(rows) - len(mine)} more box rows were found on this page than the schedule has "
                             f"runs left - the extra lines were ignored"))
    read = unsure = 0
    for row, cells_of_row in zip(mine, rows):
        label = ts._row_label(row)
        a = row.activity
        got = sc.read_row(img, cells_of_row, label, is_trip=a.trip is not None,
                          is_charging=a.activity_type == ActivityType.CHARGING)
        _write_row(db, sheet, row, got, issues)
        read += got.read
        unsure += got.unsure
        issues.extend(got.issues)
    seen[sheet.sheet_id] = start + len(mine)
    touched[sheet.sheet_id] = sheet
    sheet.scanned_page_id = page.page_id
    page.fields_read, page.fields_unsure = read, unsure
    page.status = "WARNED" if unsure else "OK"
    page.issues = json.dumps(issues)


def _reset_rows(sheet: TripSheet) -> None:
    """A re-scan replaces what an earlier scan read, rather than merging two readings."""
    for r in sheet.rows:
        if r.activity is None:          # extra runs were added by hand, never by a scan
            continue
        r.status = RowStatus.PENDING
        for k in ("actual_start_day_offset", "actual_start_time", "actual_end_day_offset", "actual_end_time",
                  "start_odometer_km", "end_odometer_km", "start_soc_pct", "end_soc_pct",
                  "stopped_at_route_stop_id", "reason_id", "attributable_to"):
            setattr(r, k, None)


def _write_row(db: Session, sheet: TripSheet, row: TripSheetRow, got, issues: list[dict]) -> None:
    v = got.values
    label = ts._row_label(row)
    if "status" in v:
        row.status = v["status"]
    for k in ("actual_end_day_offset",):
        if k in v:
            setattr(row, k, v[k])
    for key in ("actual_start_time", "actual_end_time"):
        if key in v:
            setattr(row, key, dt.datetime.strptime(v[key], "%H:%M").time())
    # the departure's day follows from the arrival: a departure later in the clock than the arrival
    # means the run started the day before it ended
    if row.actual_start_time and row.actual_end_time:
        row.actual_start_day_offset = max(0, (row.actual_end_day_offset or 0)
                                          - (1 if row.actual_start_time > row.actual_end_time else 0))
    for key in ("start_odometer_km", "end_odometer_km"):
        if key in v:
            setattr(row, key, Decimal(str(v[key])))
    for key in ("start_soc_pct", "end_soc_pct"):
        if key in v:
            setattr(row, key, Decimal(str(v[key])))
    if "reason_id" in v:
        company = sheet.schedule.cost_center.company_id if sheet.schedule.cost_center else None
        reason = db.get(TripReason, v["reason_id"])
        if reason is None or reason.company_id != company or not reason.is_active:
            issues.append(_issue("WARNING", "REASON_UNKNOWN",
                                 f"{label}: reason number {v['reason_id']:03d} is not in this company's list "
                                 f"- pick the reason by hand", run=label, field="reason_id"))
        else:
            row.reason_id = reason.reason_id
            row.attributable_to = reason.default_attributable_to
    if "stop_sequence" in v:
        wanted = v["stop_sequence"]
        match = next((st for st in (row.activity.stop_times if row.activity else []) if st.stop_sequence == wanted), None)
        if match is None:
            issues.append(_issue("WARNING", "STOP_UNKNOWN",
                                 f"{label}: stop number {wanted} is not on this trip - pick the stop by hand",
                                 run=label, field="stopped_at_route_stop_id"))
        else:
            row.stopped_at_route_stop_id = match.route_stop_id
    if row.status == RowStatus.PARTIAL and row.stopped_at_route_stop_id is None:
        issues.append(_issue("WARNING", "PARTIAL_NO_STOP",
                             f"{label}: marked cut short but the stop number could not be read - pick the last "
                             f"stop reached", run=label, field="stopped_at_route_stop_id"))


def supersede(db: Session, scan: SheetScan, keep: list[int] | None = None) -> None:
    """Point the earlier uploads for the same cost center and day at this one.

    `keep` holds the other uploads of the same batch: several files uploaded together are one batch
    and must not replace each other.
    """
    skip = set(keep or []) | {scan.scan_id}
    q = db.query(SheetScan).filter(SheetScan.scan_id.notin_(skip),
                                   SheetScan.cost_center_id == scan.cost_center_id,
                                   SheetScan.status.in_(["DONE", "PROCESSING"]))
    if scan.operating_date:
        q = q.filter(SheetScan.operating_date == scan.operating_date)
    if scan.schedule_id:
        q = q.filter(SheetScan.schedule_id == scan.schedule_id)
    for old in q.all():
        old.status, old.superseded_by = "SUPERSEDED", scan.scan_id


def page_out(p: SheetScanPage) -> dict:
    issues = json.loads(p.issues or "[]")
    return {"page_id": p.page_id, "page_no": p.page_no, "sheet_id": p.sheet_id, "schedule_id": p.schedule_id,
            "version_number": p.version_number, "operating_date": p.read_date, "status": p.status,
            "fields_read": p.fields_read, "fields_unsure": p.fields_unsure,
            "errors": sum(1 for x in issues if x["severity"] == "ERROR"),
            "warnings": sum(1 for x in issues if x["severity"] == "WARNING"), "issues": issues}


def scan_out(db: Session, scan: SheetScan, pages: bool = True) -> dict:
    out = {"scan_id": scan.scan_id, "cost_center_id": scan.cost_center_id, "operating_date": scan.operating_date,
           "schedule_id": scan.schedule_id, "file_name": scan.file_name, "page_count": scan.page_count,
           "status": scan.status, "message": scan.message, "superseded_by": scan.superseded_by,
           "uploaded_at": scan.created_at}
    if pages:
        out["pages"] = [page_out(p) for p in scan.pages]
    else:
        rows = [page_out(p) for p in scan.pages]
        out["errors"] = sum(p["errors"] for p in rows)
        out["warnings"] = sum(p["warnings"] for p in rows)
    return out


def date_of(scan: SheetScan) -> dt.date | None:
    return scan.operating_date
