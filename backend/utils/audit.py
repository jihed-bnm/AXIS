"""
Shared audit helper. Every write tool must call log_action() after a confirmed mutation.
Importing AuditLog from crm_models is intentional — it is the single audit table for all modules.
"""
from typing import Optional
from sqlalchemy.orm import Session

from backend.models.crm_models import AuditLog


def log_action(
    db: Session,
    action: str,
    entity: str,
    entity_id: Optional[int],
    payload: dict,
    result: str,
    user_id: Optional[int] = None,
) -> None:
    """Write one audit row and commit. Caller owns the session lifecycle."""
    log = AuditLog(
        user_id=user_id,
        action=action,
        entity=entity,
        entity_id=entity_id,
        payload=payload,
        result=result,
    )
    db.add(log)
    db.commit()
