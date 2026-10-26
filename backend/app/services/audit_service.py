import json

from sqlalchemy.orm import Session

from app.models.models import AuditLog, User


def record(db: Session, user: User | None, action: str, entity_type: str, entity_id=None, detail=None) -> None:
    """Append an audit row in the caller's transaction (committed with it)."""
    if detail is not None and not isinstance(detail, str):
        detail = json.dumps(detail, default=str)
    # the cost center whose role check allowed this action (set by core/access.Scope.require)
    db.add(AuditLog(user_id=user.id if user else None, username=user.username if user else None,
                    action=action, entity_type=entity_type,
                    entity_id=str(entity_id) if entity_id is not None else None, detail=detail,
                    cost_center_id=db.info.get("cost_center_id")))
