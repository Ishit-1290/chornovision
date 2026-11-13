"""Evidence metadata persistence helpers (parameterised queries only)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.evidence import Evidence, RetentionStatus


def save(db: Session, evidence: Evidence) -> Evidence:
    """Commit pending changes to ``evidence`` and refresh it."""
    db.commit()
    db.refresh(evidence)
    return evidence


def get_by_id(db: Session, evidence_id: int) -> Evidence | None:
    """Return the evidence row with primary key ``evidence_id``, or ``None``."""
    return db.get(Evidence, evidence_id)


def get_by_event_and_type(db: Session, event_pk: int, media_type: str) -> Evidence | None:
    """Return the evidence row for ``(event, media_type)``, or ``None``."""
    return db.execute(
        select(Evidence).where(Evidence.event_id == event_pk, Evidence.media_type == media_type)
    ).scalar_one_or_none()


def list_by_event(db: Session, event_pk: int) -> list[Evidence]:
    """Return every evidence row for an event, oldest first."""
    return list(
        db.execute(
            select(Evidence).where(Evidence.event_id == event_pk).order_by(Evidence.id)
        ).scalars()
    )


def list_retained(db: Session) -> list[Evidence]:
    """Return all non-deleted evidence rows, oldest captured first.

    ``protected`` rows are included so the retention service can account for their bytes
    and skip them explicitly rather than silently ignoring them.
    """
    return list(
        db.execute(
            select(Evidence)
            .where(Evidence.retention_status != RetentionStatus.DELETED.value)
            .order_by(Evidence.captured_at.asc(), Evidence.id.asc())
        ).scalars()
    )


def total_stored_bytes(db: Session) -> int:
    """Return the sum of ``file_size_bytes`` over non-deleted evidence."""
    value = db.execute(
        select(func.coalesce(func.sum(Evidence.file_size_bytes), 0)).where(
            Evidence.retention_status != RetentionStatus.DELETED.value
        )
    ).scalar_one()
    return int(value or 0)
