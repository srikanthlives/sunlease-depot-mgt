from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core import deps
from app.core.access import Scope, memberships, scope, super_admin
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models.enums import Role
from app.models.models import AuditLog, CostCenter, User, UserCostCenterRole
from app.schemas.schemas import CostCenterRoleIn, LoginIn, UserIn, UserOut, UserUpdate
from app.services import audit_service

router = APIRouter(prefix="/api", tags=["auth"])


def _me(db: Session, user: User) -> dict:
    return {"user": UserOut.model_validate(user).model_dump(), "is_super_admin": user.role == Role.SUPER_ADMIN,
            "cost_centers": memberships(db, user)}


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == body.username).first()
    if not user or not user.is_active or not verify_password(body.password, user.hashed_password):
        raise HTTPException(401, "Invalid username or password")
    token = create_access_token(str(user.id), {"role": user.role})
    return {"access_token": token, "token_type": "bearer", **_me(db, user)}


@router.get("/auth/me")
def me(db: Session = Depends(get_db), user: User = Depends(deps.get_current_user)):
    """The signed-in user with the cost centers they can switch between (and their role in each)."""
    return _me(db, user)


# ---------------- users (super admin) ----------------
def _user_out(u: User) -> dict:
    return {**UserOut.model_validate(u).model_dump(),
            "cost_center_roles": sorted(({"cost_center_id": r.cost_center_id, "role": r.role} for r in u.cost_center_roles),
                                        key=lambda r: r["cost_center_id"])}


def _set_roles(db: Session, u: User, roles: list[CostCenterRoleIn]):
    ids = [r.cost_center_id for r in roles]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "A user can have only one role per cost center")
    if ids and db.query(CostCenter).filter(CostCenter.cost_center_id.in_(ids)).count() != len(ids):
        raise HTTPException(422, "Unknown cost center")
    u.cost_center_roles = [UserCostCenterRole(cost_center_id=r.cost_center_id, role=r.role) for r in roles]


@router.get("/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(super_admin)):
    return [_user_out(u) for u in db.query(User).order_by(User.username).all()]


@router.post("/users", status_code=201)
def create_user(body: UserIn, db: Session = Depends(get_db), me: User = Depends(super_admin)):
    if db.query(User).filter(User.username == body.username).first():
        raise HTTPException(409, "Username already exists")
    u = User(username=body.username, full_name=body.full_name, hashed_password=hash_password(body.password),
             role=Role.SUPER_ADMIN if body.is_super_admin else Role.USER)
    db.add(u)
    _set_roles(db, u, body.cost_center_roles)
    db.flush()
    audit_service.record(db, me, "CREATE", "User", u.id, {"username": u.username, "role": u.role,
                                                          "cost_center_roles": [r.model_dump() for r in body.cost_center_roles]})
    db.commit()
    return _user_out(u)


@router.put("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db), me: User = Depends(super_admin)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    data = body.model_dump(exclude_unset=True)
    if u.id == me.id and (data.get("is_super_admin") is False or data.get("is_active") is False):
        raise HTTPException(409, "You cannot remove your own super admin access or deactivate yourself")
    if "password" in data:
        u.hashed_password = hash_password(data.pop("password"))
    if "is_super_admin" in data:
        u.role = Role.SUPER_ADMIN if data.pop("is_super_admin") else Role.USER
    if "cost_center_roles" in data:
        data.pop("cost_center_roles")
        _set_roles(db, u, body.cost_center_roles)
    for k, v in data.items():
        setattr(u, k, v)
    audit_service.record(db, me, "UPDATE", "User", u.id,
                         {k: v for k, v in body.model_dump(exclude_unset=True).items() if k != "password"})
    db.commit()
    return _user_out(u)


# ---------------- audit log (cost-center admins see their cost centers) ----------------
@router.get("/audit-logs")
def audit_logs(entity_type: str | None = None, limit: int = 200, db: Session = Depends(get_db),
               sc: Scope = Depends(scope)):
    q = db.query(AuditLog)
    if not (sc.is_super and sc.selected is None):
        allowed = [cc for cc in sc.visible if sc.rank(cc) >= Role.RANK[Role.ADMIN]]
        if not allowed:
            raise HTTPException(403, "Admin role required")
        q = q.filter(AuditLog.cost_center_id.in_(allowed))
    if entity_type:
        q = q.filter(AuditLog.entity_type == entity_type)
    rows = q.order_by(AuditLog.id.desc()).limit(min(limit, 1000)).all()
    return [{"id": r.id, "at": r.at.isoformat(), "username": r.username, "action": r.action,
             "entity_type": r.entity_type, "entity_id": r.entity_id, "detail": r.detail,
             "cost_center_id": r.cost_center_id} for r in rows]
