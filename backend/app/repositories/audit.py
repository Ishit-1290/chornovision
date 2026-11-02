"""Audit-log persistence helper."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def record(
    db: Session,
    *,
    action: str,
    user_id: int | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    metadata: dict[str, object] | None = None,
) -> AuditLog:
    """Write an audit record.

    Callers must never pass passwords, session tokens, or camera credentials here.
    """
    log = AuditLog(
        action=action,
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        log_metadata=metadata,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log
