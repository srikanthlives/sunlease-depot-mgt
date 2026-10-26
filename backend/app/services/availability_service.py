"""The employee availability register: date ranges in which someone cannot take a duty.

A depot-level marker kept by the clerk, not HRMS leave approval. The roster reads it
for warnings; it never blocks a save on its own, because the depot sometimes has to
call a driver in on an off day and record why.
"""
import datetime as dt

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.models import Employee, EmployeeAvailability


def check_overlap(db: Session, employee_id: int, start: dt.date, end: dt.date,
                  exclude_id: int | None = None) -> None:
    """One employee cannot have two availability rows covering the same day."""
    q = db.query(EmployeeAvailability).filter(
        EmployeeAvailability.employee_id == employee_id,
        EmployeeAvailability.from_date <= end,
        EmployeeAvailability.to_date >= start,
    )
    if exclude_id:
        q = q.filter(EmployeeAvailability.availability_id != exclude_id)
    other = q.first()
    if other is not None:
        raise HTTPException(409, f"Overlaps an existing {other.status.replace('_', ' ').lower()} entry "
                                 f"({other.from_date:%d-%b-%Y} to {other.to_date:%d-%b-%Y})")


def unavailable_on(db: Session, employee_id: int, on: dt.date) -> EmployeeAvailability | None:
    """The register entry covering `on`, if any."""
    return (db.query(EmployeeAvailability)
            .filter(EmployeeAvailability.employee_id == employee_id,
                    EmployeeAvailability.from_date <= on, EmployeeAvailability.to_date >= on)
            .first())


def register_for_range(db: Session, cc_ids: list[int], date_from: dt.date,
                       date_to: dt.date) -> dict[int, list[EmployeeAvailability]]:
    """Every entry touching the range, grouped by employee: one query for a whole roster period."""
    rows = (db.query(EmployeeAvailability)
            .filter(EmployeeAvailability.cost_center_id.in_(cc_ids),
                    EmployeeAvailability.from_date <= date_to, EmployeeAvailability.to_date >= date_from)
            .order_by(EmployeeAvailability.from_date).all())
    out: dict[int, list[EmployeeAvailability]] = {}
    for r in rows:
        out.setdefault(r.employee_id, []).append(r)
    return out


def employed_on(e: Employee, on: dt.date) -> bool:
    """Stint dates only: the employee was on the rolls on `on`."""
    return e.start_date <= on and (e.end_date is None or on <= e.end_date)


def free_on(db: Session, e: Employee, on: dt.date) -> tuple[bool, str | None]:
    """(can take a duty, why not). Used by the roster pickers and validator."""
    if e.status != "ACTIVE":
        return False, f"{e.full_name} is {e.status.lower()}"
    if not employed_on(e, on):
        return False, (f"{e.full_name} is not on the rolls on {on:%d-%b-%Y} "
                       f"(stint {e.start_date:%d-%b-%Y} to "
                       f"{e.end_date:%d-%b-%Y})" if e.end_date else
                       f"{e.full_name} is not on the rolls on {on:%d-%b-%Y} (joined {e.start_date:%d-%b-%Y})")
    entry = unavailable_on(db, e.employee_id, on)
    if entry is not None:
        return False, f"{e.full_name} is marked {entry.status.replace('_', ' ').lower()} on {on:%d-%b-%Y}"
    return True, None
