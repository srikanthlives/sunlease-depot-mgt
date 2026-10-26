"""Cost-center scoping and per-cost-center roles.

Every request carries the cost center the user is working in as the `X-Cost-Center-Id`
header, or `all` for the read-only "All my cost centers" view. Reads are filtered to the
visible cost centers; every write checks the user's role in the cost center that owns the
record (not the one in the header), so a record opened from the "all" view is still
guarded by the right role. SUPER_ADMIN bypasses every check.
"""
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models.enums import Role
from app.models.models import CostCenter, User, UserCostCenterRole

SUPER_RANK = 99


def memberships(db: Session, user: User) -> list[dict]:
    """Active cost centers the user may work in, with their role (super admin: all, as ADMIN)."""
    q = db.query(CostCenter).filter(CostCenter.is_active.is_(True))
    if user.role == Role.SUPER_ADMIN:
        rows = [(cc, Role.ADMIN) for cc in q.all()]
    else:
        rows = [(r.cost_center, r.role) for r in db.query(UserCostCenterRole).filter(UserCostCenterRole.user_id == user.id)
                if r.cost_center.is_active]
    rows = [(cc, role) for cc, role in rows if cc.company.is_active]
    rows.sort(key=lambda x: (x[0].company.company_name, x[0].cost_center_code))
    return [{"cost_center_id": cc.cost_center_id, "cost_center_code": cc.cost_center_code,
             "cost_center_name": cc.cost_center_name, "company_id": cc.company_id,
             "company_code": cc.company.company_code, "company_name": cc.company.company_name, "role": role}
            for cc, role in rows]


class Scope:
    def __init__(self, db: Session, user: User, selected: int | None):
        self.db, self.user = db, user
        self.is_super = user.role == Role.SUPER_ADMIN
        self.members = memberships(db, user)
        self.roles = {m["cost_center_id"]: m["role"] for m in self.members}
        self.companies = {m["cost_center_id"]: m["company_id"] for m in self.members}
        if selected is not None and selected not in self.roles:
            raise HTTPException(403, "You have no role in that cost center")
        self.selected = selected

    # ---- reads
    @property
    def visible(self) -> list[int]:
        """Cost centers shown in this request: the selected one, or all of the user's."""
        return [self.selected] if self.selected is not None else list(self.roles)

    def filter(self, query, column):
        return query.filter(column.in_(self.visible))

    @property
    def visible_companies(self) -> list[int]:
        return sorted({self.companies[c] for c in self.visible})

    # ---- role checks
    def rank(self, cost_center_id: int | None) -> int:
        if self.is_super:
            return SUPER_RANK
        return Role.RANK.get(self.roles.get(cost_center_id), 0)

    def require(self, cost_center_id: int | None, minimum: str, what: str = "Record"):
        """Gate an action on a record owned by `cost_center_id`. Records the user cannot see
        at all are reported as not found, so other tenants' data is not revealed."""
        if not self.is_super and cost_center_id not in self.roles:
            raise HTTPException(404, f"{what} not found")
        if self.rank(cost_center_id) < Role.RANK[minimum]:
            raise HTTPException(403, f"{minimum.title()} role or higher required in this cost center")
        self.db.info["cost_center_id"] = cost_center_id  # picked up by the audit log
        return cost_center_id

    def require_company(self, company_id: int | None, minimum: str, what: str = "Record"):
        """Company-level records (locations): the best role held in any cost center of that company."""
        ranks = [self.rank(cc) for cc, co in self.companies.items() if co == company_id]
        if not self.is_super and not ranks:
            raise HTTPException(404, f"{what} not found")
        if not self.is_super and max(ranks) < Role.RANK[minimum]:
            raise HTTPException(403, f"{minimum.title()} role or higher required in this company")

    def target(self, minimum: str) -> int:
        """The cost center a new record goes into: the selected one (not the "all" view)."""
        if self.selected is None:
            raise HTTPException(422, "Pick a cost center first - new records cannot be added in the All view")
        return self.require(self.selected, minimum)

    def target_company(self, minimum: str) -> int:
        cc = self.target(minimum)
        return self.companies[cc]

    def require_super(self):
        if not self.is_super:
            raise HTTPException(403, "Super admin only")


def scope(x_cost_center_id: str | None = Header(default=None), db: Session = Depends(get_db),
          user: User = Depends(get_current_user)) -> Scope:
    raw = (x_cost_center_id or "").strip().lower()
    if raw in ("", "all"):
        selected = None
    else:
        try:
            selected = int(raw)
        except ValueError:
            raise HTTPException(400, "X-Cost-Center-Id must be a number or 'all'")
    return Scope(db, user, selected)


def super_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.SUPER_ADMIN:
        raise HTTPException(403, "Super admin only")
    return user
