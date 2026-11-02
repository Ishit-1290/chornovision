"""Event persistence helpers (parameterised queries only)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.event import Event, EventTransitionRecord


def add(db: Session, event: Event) -> Event:
    """Persist a new ``event`` row and return it."""
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def save(db: Session, event: Event) -> Event:
    """Commit pending changes to ``event`` and refresh it."""
    db.commit()
    db.refresh(event)
    return event


def get_by_event_id(db: Session, event_id: str) -> Event | None:
    """Return the event with the deterministic ``event_id``, or ``None``."""
    return db.execute(select(Event).where(Event.event_id == event_id)).scalar_one_or_none()


def get_by_id(db: Session, event_pk: int) -> Event | None:
    """Return the event with internal primary key ``event_pk``, or ``None``."""
    return db.get(Event, event_pk)


def add_transition(db: Session, record: EventTransitionRecord) -> EventTransitionRecord:
    """Persist one history row (does not commit on its own)."""
    db.add(record)
    return record


def list_transitions(db: Session, event_pk: int) -> list[EventTransitionRecord]:
    """Return the transition history for an event, oldest first."""
    return list(
        db.execute(
            select(EventTransitionRecord)
            .where(EventTransitionRecord.event_id == event_pk)
            .order_by(EventTransitionRecord.state_version)
        ).scalars()
    )


def _filtered(
    *,
    camera_id: int | None,
    event_type: str | None,
    status: str | None,
    review_status: str | None,
    since: datetime | None,
    until: datetime | None,
) -> Select:
    query = select(Event)
    if camera_id is not None:
        query = query.where(Event.camera_id == camera_id)
    if event_type is not None:
        query = query.where(Event.event_type == event_type)
    if status is not None:
        query = query.where(Event.status == status)
    if review_status is not None:
        query = query.where(Event.review_status == review_status)
    if since is not None:
        query = query.where(Event.trigger_time >= since)
    if until is not None:
        query = query.where(Event.trigger_time <= until)
    return query


def list_events(
    db: Session,
    *,
    camera_id: int | None = None,
    event_type: str | None = None,
    status: str | None = None,
    review_status: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    order: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> list[Event]:
    """Return events newest-first by default, with optional filters and pagination."""
    query = _filtered(
        camera_id=camera_id,
        event_type=event_type,
        status=status,
        review_status=review_status,
        since=since,
        until=until,
    )
    if order == "asc":
        query = query.order_by(Event.trigger_time.asc(), Event.id.asc())
    else:
        query = query.order_by(Event.trigger_time.desc(), Event.id.desc())
    query = query.limit(limit).offset(offset)
    return list(db.execute(query).scalars())


def count_events(
    db: Session,
    *,
    camera_id: int | None = None,
    event_type: str | None = None,
    status: str | None = None,
    review_status: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> int:
    """Return the total number of events matching the filters."""
    query = _filtered(
        camera_id=camera_id,
        event_type=event_type,
        status=status,
        review_status=review_status,
        since=since,
        until=until,
    )
    return int(db.execute(select(func.count()).select_from(query.subquery())).scalar_one())


def summary_counts(db: Session) -> dict[str, Any]:
    """Return per-status event counts (used by tests/health-style summaries)."""
    rows = db.execute(select(Event.status, func.count()).group_by(Event.status)).all()
    return {status: int(count) for status, count in rows}
