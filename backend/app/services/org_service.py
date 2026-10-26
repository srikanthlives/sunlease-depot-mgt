"""Default organisation and the one-time upgrade of single-tenant data."""
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.models.enums import Role
from app.models.models import (
    BusSchedule, Company, CostCenter, CostCenterSetting, Employee, Location, Route, User,
    UserCostCenterRole, Vehicle,
)

DEFAULT_COMPANY = ("SUNLEASE", "Sunlease Renewables")
DEFAULT_COST_CENTER = ("DEFAULT", "Default")


def default_cost_center(db: Session) -> CostCenter:
    """The first cost center, creating the default company and cost center when there are none."""
    cc = db.query(CostCenter).order_by(CostCenter.cost_center_id).first()
    if cc:
        return cc
    company = db.query(Company).order_by(Company.company_id).first()
    if company is None:
        company = Company(company_code=DEFAULT_COMPANY[0], company_name=DEFAULT_COMPANY[1])
        db.add(company)
        db.flush()
    cc = CostCenter(company_id=company.company_id, cost_center_code=DEFAULT_COST_CENTER[0],
                    cost_center_name=DEFAULT_COST_CENTER[1])
    db.add(cc)
    db.flush()
    return cc


def backfill_tenancy(db: Session, verbose: bool = False) -> None:
    """Move pre-tenancy data into the default cost center. Idempotent: only rows without an owner
    and users still carrying an old global role are touched."""
    tenant_tables = (Vehicle, Route, BusSchedule, Employee)
    orphans = any(db.query(m).filter(m.cost_center_id.is_(None)).first() for m in tenant_tables)
    orphan_locs = db.query(Location).filter(Location.company_id.is_(None)).first() is not None
    legacy_users = db.query(User).filter(User.role.notin_((Role.SUPER_ADMIN, Role.USER))).all()
    if not (orphans or orphan_locs or legacy_users):
        return
    cc = default_cost_center(db)
    for m in tenant_tables:
        n = db.query(m).filter(m.cost_center_id.is_(None)).update({m.cost_center_id: cc.cost_center_id})
        if n and verbose:
            print(f"[MIGRATE] {n} {m.__tablename__} -> cost center {cc.cost_center_code}")
    n = db.query(Location).filter(Location.company_id.is_(None)).update({Location.company_id: cc.company_id})
    if n and verbose:
        print(f"[MIGRATE] {n} locations -> company {cc.company.company_code}")
    for u in legacy_users:
        # the original admin login becomes the super admin; everyone else keeps their role in the default cost center
        if u.username == "admin":
            u.role = Role.SUPER_ADMIN
        else:
            if not db.query(UserCostCenterRole).filter_by(user_id=u.id, cost_center_id=cc.cost_center_id).first():
                db.add(UserCostCenterRole(user_id=u.id, cost_center_id=cc.cost_center_id,
                                          role=u.role if u.role in Role.ALL else Role.VIEWER))
            u.role = Role.USER
        if verbose:
            print(f"[MIGRATE] user {u.username} -> {u.role}")
    # pre-tenancy global settings (table app_settings, dropped by migrate.py afterwards)
    if inspect(db.get_bind()).has_table("app_settings") and \
            not db.query(CostCenterSetting).filter_by(cost_center_id=cc.cost_center_id).first():
        for key, value in db.execute(text("SELECT key, value FROM app_settings")).all():
            db.add(CostCenterSetting(cost_center_id=cc.cost_center_id, key=key, value=value))
    db.commit()
