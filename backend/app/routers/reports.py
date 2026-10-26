"""Reports over trip sheets: billing (approved sheets only, km), missing sheets, crew hours, printable sheets."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.access import Scope, scope
from app.db.session import get_db
from app.models.enums import Role
from app.models.models import BusSchedule
from app.services import report_service as rs

router = APIRouter(prefix="/api", tags=["reports"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _ccs(sc: Scope, minimum: str = Role.VIEWER) -> list[int]:
    ids = [cc for cc in sc.visible if sc.rank(cc) >= Role.RANK[minimum]]
    if not ids:
        raise HTTPException(403, f"{minimum.title()} role or higher required")
    return ids


def _xlsx(content: bytes, name: str) -> Response:
    return Response(content, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/reports/billing")
def billing(date_from: dt.date, date_to: dt.date, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    return rs.billing(db, _ccs(sc), date_from, date_to)


@router.get("/reports/billing.xlsx")
def billing_xlsx(date_from: dt.date, date_to: dt.date, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """Export only covers cost centers where the user is a publisher or above."""
    rep = rs.billing(db, _ccs(sc, Role.PUBLISHER), date_from, date_to)
    return _xlsx(rs.billing_xlsx(rep), f"billing_{date_from}_{date_to}.xlsx")


@router.get("/reports/missing-sheets")
def missing(date_from: dt.date, date_to: dt.date, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    return rs.missing_sheets(db, _ccs(sc), date_from, date_to)


@router.get("/reports/crew-hours")
def crew_hours(date_from: dt.date, date_to: dt.date, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    return rs.crew_hours(db, _ccs(sc), date_from, date_to)


@router.get("/reports/crew-hours.xlsx")
def crew_hours_xlsx(date_from: dt.date, date_to: dt.date, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    rep = rs.crew_hours(db, _ccs(sc, Role.PUBLISHER), date_from, date_to)
    return _xlsx(rs.crew_xlsx(rep), f"crew_hours_{date_from}_{date_to}.xlsx")


@router.get("/reports/duty-day")
def duty_day(on: dt.date, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """End of day: every duty slot, who was planned, who worked it and why not."""
    return rs.duty_day_summary(db, _ccs(sc), on)


@router.get("/reports/duty-day.xlsx")
def duty_day_xlsx(on: dt.date, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    rep = rs.duty_day_summary(db, _ccs(sc), on)
    return _xlsx(rs.duty_day_xlsx(rep), f"duty_day_{on}.xlsx")


@router.get("/reports/duty-statistics")
def duty_statistics(date_from: dt.date, date_to: dt.date, db: Session = Depends(get_db),
                    sc: Scope = Depends(scope)):
    """Per employee over a stretch of days: duties planned, worked, stood in for and missed."""
    return rs.duty_statistics(db, _ccs(sc), date_from, date_to)


@router.get("/reports/duty-statistics.xlsx")
def duty_statistics_xlsx(date_from: dt.date, date_to: dt.date, db: Session = Depends(get_db),
                         sc: Scope = Depends(scope)):
    rep = rs.duty_statistics(db, _ccs(sc), date_from, date_to)
    return _xlsx(rs.duty_statistics_xlsx(rep), f"duty_statistics_{date_from}_{date_to}.xlsx")


@router.get("/trip-sheets/print-data")
def print_data(date: dt.date, schedule_id: int | None = None, db: Session = Depends(get_db), sc: Scope = Depends(scope)):
    """The published plan for one schedule (or every visible schedule) on `date`, for the paper sheet."""
    if schedule_id is not None:
        s = db.get(BusSchedule, schedule_id)
        if not s:
            raise HTTPException(404, "Schedule not found")
        sc.require(s.cost_center_id, Role.VIEWER, "Schedule")
        schedules = [s]
    else:
        schedules = sc.filter(db.query(BusSchedule), BusSchedule.cost_center_id).order_by(BusSchedule.schedule_code).all()
    out = [d for d in (rs.print_data(db, s, date) for s in schedules) if d]
    db.commit()   # default reasons may have been created
    if schedule_id is not None and not out:
        raise HTTPException(404, "No published version applies on that date")
    return out
