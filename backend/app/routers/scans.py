"""Uploading scanned paper trip sheets and reading them into draft sheets.

Its own router, registered before the trip-sheet one, so that `/trip-sheets/scans` is not read as a
sheet id.
"""
import datetime as dt
import os
import shutil

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.access import Scope, scope
from app.db.session import get_db
from app.models.enums import Role
from app.models.models import BusSchedule, SheetScan
from app.services import audit_service, scan_intake, scan_service

router = APIRouter(prefix="/api", tags=["trip-sheets"])


# ---------------- scanned paper sheets ----------------
MAX_SCAN_MB = 40


@router.post("/trip-sheets/scans", status_code=201)
async def upload_scans(files: list[UploadFile] = File(...), operating_date: dt.date | None = Form(None),
                       schedule_id: int | None = Form(None), db: Session = Depends(get_db),
                       sc: Scope = Depends(scope)):
    """Upload one or more scanned PDFs of paper sheets - a whole day for the cost center, or one bus.

    Each file becomes its own upload, read straight away and written onto draft sheets. A new upload
    for the same cost center and day supersedes the previous one and re-reads the sheets it covers,
    so the files of one batch are read first and only then do they replace what went before.
    """
    cc = sc.target(Role.MIS)
    if schedule_id is not None:
        schedule = db.get(BusSchedule, schedule_id)
        if schedule is None or schedule.cost_center_id != cc:
            raise HTTPException(404, "Schedule not found")
    if not files:
        raise HTTPException(422, "Choose at least one scanned PDF")
    for f in files:
        if not (f.filename or "").lower().endswith(".pdf"):
            raise HTTPException(422, f"{f.filename or 'The file'} is not a PDF - scan the sheets to PDF")

    done = []
    for f in files:
        data = await f.read()
        if len(data) > MAX_SCAN_MB * 1024 * 1024:
            raise HTTPException(422, f"{f.filename} is larger than {MAX_SCAN_MB} MB - "
                                     f"scan at 200-300 dpi in grayscale")
        scan = SheetScan(cost_center_id=cc, operating_date=operating_date, schedule_id=schedule_id,
                         file_name=(f.filename or "scan.pdf")[:255], uploaded_by=sc.user.id)
        db.add(scan)
        db.flush()
        with open(os.path.join(scan_service.scan_dir(scan.scan_id), "upload.pdf"), "wb") as fh:
            fh.write(data)
        scan_intake.process(db, scan, data, sc.user)
        audit_service.record(db, sc.user, "CREATE", "SheetScan", scan.scan_id,
                             {"file": scan.file_name, "pages": scan.page_count, "status": scan.status})
        done.append(scan)
    # only now: a batch of several files must not supersede its own members
    for scan in done:
        if scan.status == "DONE":
            scan_intake.supersede(db, scan, keep=[x.scan_id for x in done])
    db.commit()
    for scan in done:
        db.refresh(scan)
    return [scan_intake.scan_out(db, x) for x in done]


@router.get("/trip-sheets/scans")
def list_scans(operating_date: dt.date | None = None, include_superseded: bool = False,
               db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    q = sc.filter(db.query(SheetScan), SheetScan.cost_center_id)
    if operating_date:
        q = q.filter(SheetScan.operating_date == operating_date)
    if not include_superseded:
        q = q.filter(SheetScan.status != "SUPERSEDED")
    return [scan_intake.scan_out(db, x, pages=False) for x in q.order_by(SheetScan.scan_id.desc()).limit(100)]


def _get_scan(db: Session, sc: Scope, scan_id: int, minimum: str = Role.VIEWER) -> SheetScan:
    scan = db.get(SheetScan, scan_id)
    if scan is None:
        raise HTTPException(404, "Scan not found")
    sc.require(scan.cost_center_id, minimum, "Scan")
    return scan


@router.get("/trip-sheets/scans/{scan_id}")
def get_scan(scan_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    return scan_intake.scan_out(db, _get_scan(db, sc, scan_id))


@router.get("/trip-sheets/scans/{scan_id}/pages/{page_no}/image")
def scan_page_image(scan_id: int, page_no: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """The straightened page, so a clerk can compare the paper with what was read."""
    scan = _get_scan(db, sc, scan_id)
    page = next((p for p in scan.pages if p.page_no == page_no), None)
    if page is None or not page.image_path or not os.path.exists(page.image_path):
        raise HTTPException(404, "Page image not found")
    return FileResponse(page.image_path, media_type="image/png")


@router.post("/trip-sheets/scans/{scan_id}/reprocess")
def reprocess_scan(scan_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """Read the same upload again - useful after a reason code or a schedule version was corrected."""
    scan = _get_scan(db, sc, scan_id, Role.MIS)
    path = os.path.join(scan_service.scan_dir(scan.scan_id), "upload.pdf")
    if not os.path.exists(path):
        raise HTTPException(409, "The uploaded file is no longer on the server - upload it again")
    scan.pages.clear()
    scan.status, scan.message = "PROCESSING", None
    db.flush()
    with open(path, "rb") as fh:
        scan_intake.process(db, scan, fh.read(), sc.user)
    db.commit()
    db.refresh(scan)
    return scan_intake.scan_out(db, scan)


@router.delete("/trip-sheets/scans/{scan_id}", status_code=204)
def delete_scan(scan_id: int, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """Forget the upload. The draft sheets it filled stay as they are, for a clerk to finish by hand."""
    scan = _get_scan(db, sc, scan_id, Role.MIS)
    audit_service.record(db, sc.user, "DELETE", "SheetScan", scan_id, {"file": scan.file_name})
    shutil.rmtree(scan_service.scan_dir(scan_id), ignore_errors=True)
    db.delete(scan)
    db.commit()


