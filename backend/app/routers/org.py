"""Companies and cost centers - super admin only."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.access import super_admin
from app.db.session import get_db
from app.models.models import (
    AuditLog, BusSchedule, Company, CostCenter, CostCenterSetting, Employee, Location, Route, User, UserCostCenterRole, Vehicle,
)
from app.schemas.schemas import CompanyIn, CostCenterIn
from app.services import audit_service

router = APIRouter(prefix="/api", tags=["organisation"])


def _company_out(c: Company) -> dict:
    return {"company_id": c.company_id, "company_code": c.company_code, "company_name": c.company_name,
            "print_language": c.print_language, "is_active": c.is_active,
            "cost_center_count": len(c.cost_centers)}


def _cc_out(db: Session, c: CostCenter) -> dict:
    return {"cost_center_id": c.cost_center_id, "company_id": c.company_id, "company_name": c.company.company_name,
            "cost_center_code": c.cost_center_code, "cost_center_name": c.cost_center_name,
            "print_language": c.print_language, "company_print_language": c.company.print_language,
            "is_active": c.is_active,
            "user_count": db.query(UserCostCenterRole).filter(UserCostCenterRole.cost_center_id == c.cost_center_id).count()}


def _commit(db: Session, what: str):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"{what} code or name already exists")


@router.get("/companies")
def list_companies(db: Session = Depends(get_db), _: User = Depends(super_admin)):
    return [_company_out(c) for c in db.query(Company).order_by(Company.company_name).all()]


@router.post("/companies", status_code=201)
def create_company(body: CompanyIn, db: Session = Depends(get_db), me: User = Depends(super_admin)):
    c = Company(**body.model_dump())
    db.add(c)
    _commit(db, "Company")
    audit_service.record(db, me, "CREATE", "Company", c.company_id, body.model_dump())
    db.commit()
    return _company_out(c)


@router.put("/companies/{company_id}")
def update_company(company_id: int, body: CompanyIn, db: Session = Depends(get_db), me: User = Depends(super_admin)):
    c = db.get(Company, company_id)
    if not c:
        raise HTTPException(404, "Company not found")
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    audit_service.record(db, me, "UPDATE", "Company", company_id, body.model_dump())
    _commit(db, "Company")
    return _company_out(c)


@router.delete("/companies/{company_id}", status_code=204)
def delete_company(company_id: int, db: Session = Depends(get_db), me: User = Depends(super_admin)):
    c = db.get(Company, company_id)
    if not c:
        raise HTTPException(404, "Company not found")
    if c.cost_centers or db.query(Location).filter(Location.company_id == company_id).first():
        raise HTTPException(409, "Company has cost centers or locations - deactivate it instead")
    audit_service.record(db, me, "DELETE", "Company", company_id, c.company_code)
    db.delete(c)
    db.commit()


@router.get("/cost-centers")
def list_cost_centers(db: Session = Depends(get_db), _: User = Depends(super_admin)):
    rows = db.query(CostCenter).join(Company).order_by(Company.company_name, CostCenter.cost_center_code).all()
    return [_cc_out(db, c) for c in rows]


@router.post("/cost-centers", status_code=201)
def create_cost_center(body: CostCenterIn, db: Session = Depends(get_db), me: User = Depends(super_admin)):
    if not db.get(Company, body.company_id):
        raise HTTPException(422, "Company does not exist")
    c = CostCenter(**body.model_dump())
    db.add(c)
    _commit(db, "Cost center")
    audit_service.record(db, me, "CREATE", "CostCenter", c.cost_center_id, body.model_dump())
    db.commit()
    return _cc_out(db, c)


@router.put("/cost-centers/{cost_center_id}")
def update_cost_center(cost_center_id: int, body: CostCenterIn, db: Session = Depends(get_db),
                       me: User = Depends(super_admin)):
    c = db.get(CostCenter, cost_center_id)
    if not c:
        raise HTTPException(404, "Cost center not found")
    if body.company_id != c.company_id:
        raise HTTPException(409, "A cost center cannot move to another company - its locations belong to the company")
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    audit_service.record(db, me, "UPDATE", "CostCenter", cost_center_id, body.model_dump())
    _commit(db, "Cost center")
    return _cc_out(db, c)


@router.delete("/cost-centers/{cost_center_id}", status_code=204)
def delete_cost_center(cost_center_id: int, db: Session = Depends(get_db), me: User = Depends(super_admin)):
    c = db.get(CostCenter, cost_center_id)
    if not c:
        raise HTTPException(404, "Cost center not found")
    for model in (Vehicle, Route, BusSchedule, Employee):
        if db.query(model).filter(model.cost_center_id == cost_center_id).first():
            raise HTTPException(409, "Cost center has buses, routes, schedules or staff - deactivate it instead")
    if db.query(AuditLog).filter(AuditLog.cost_center_id == cost_center_id).first():
        raise HTTPException(409, "Cost center has audit history - deactivate it instead")
    audit_service.record(db, me, "DELETE", "CostCenter", cost_center_id, c.cost_center_code)
    db.query(CostCenterSetting).filter(CostCenterSetting.cost_center_id == cost_center_id).delete()
    db.query(UserCostCenterRole).filter(UserCostCenterRole.cost_center_id == cost_center_id).delete()
    db.delete(c)
    db.commit()
