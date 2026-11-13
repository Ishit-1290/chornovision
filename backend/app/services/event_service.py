"""Event persistence service (Phase 6; FR-40, FR-45; OQ-09/D-12).

The worker submits deterministic lifecycle transitions over the authenticated internal
channel. This service is the single place that turns a transition into durable state:

* an ``events`` row holds the **current** state of one event;
* an ``event_transitions`` row preserves the **history** of meaningful transitions
  (``../guidelines.md`` §5.8, FR-21);
* the rendered deterministic message is stored with both, and is never regenerated when a
  template later changes (W §8).

Three invariants make repeated/out-of-order delivery safe (D-12):

1. **Idempotent by identity** — ``event_id`` is unique, so a re-delivered transition
   upserts the same row instead of creating a duplicate.
2. **Monotonic revisions** — a submission whose ``state_version`` is not newer than the
   stored value is a stale no-op; newer state is never overwritten by older state.
3. **Terminal immutability** — a ``completed``/``cancelled`` event is never mutated; a
   later recurrence is a new event with a new deterministic id (D-37).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.event_messages.renderer import render_event
from app.events.types import EventSnapshot, EventStatus, EventTransition
from app.models.event import Event, EventTransitionRecord
from app.repositories import cameras as cameras_repo
from app.repositories import events as events_repo
from app.utils import ensure_utc

TERMINAL_STATUSES = frozenset({EventStatus.COMPLETED.value, EventStatus.CANCELLED.value})


class EventServiceError(Exception):
    """Base class for event persistence errors."""


class UnknownCamera(EventServiceError):
    """The event references a camera id that does not exist."""


@dataclass(frozen=True)
class EventRecordResult:
    """Outcome of persisting one transition."""

    event: Event
    applied: bool


def _json_safe(value: Any) -> Any:
    """Coerce ``value`` to something the JSON column can store (defensive)."""
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):  # pragma: no cover - engine values are plain
        return {}


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _apply_snapshot(event: Event, snapshot: EventSnapshot, *, message: str) -> None:
    """Copy a canonical snapshot onto the ORM row (used for create and update)."""
    attributes = _json_safe(snapshot.attributes or {})
    event.event_type = snapshot.event_type.value
    event.entity_id = snapshot.entity_id
    event.zone_id = snapshot.zone_id
    event.zone_name = snapshot.zone_name
    event.start_time = ensure_utc(snapshot.start_time)
    event.trigger_time = ensure_utc(snapshot.trigger_time)
    event.last_updated_at = ensure_utc(snapshot.last_updated_at)
    event.end_time = ensure_utc(snapshot.end_time) if snapshot.end_time else None
    event.status = snapshot.status.value
    event.severity = snapshot.severity.value
    event.certainty = snapshot.certainty.value
    event.confidence = snapshot.confidence
    event.state_version = snapshot.state_version
    event.message = message
    event.attributes = attributes
    event.evidence_refs = _json_safe(list(snapshot.evidence_refs or []))
    event.review_status = snapshot.review_status.value
    event.rule_version = _optional_str(attributes.get("rule_version"))
    event.config_version = _optional_str(attributes.get("config_version"))


def _transition_record(
    event_pk: int, transition: EventTransition, *, message: str
) -> EventTransitionRecord:
    snapshot = transition.event
    return EventTransitionRecord(
        event_id=event_pk,
        state_version=snapshot.state_version,
        action=transition.action.value,
        status=snapshot.status.value,
        occurred_at=ensure_utc(snapshot.last_updated_at),
        end_time=ensure_utc(snapshot.end_time) if snapshot.end_time else None,
        confidence=snapshot.confidence,
        certainty=snapshot.certainty.value,
        message=message,
        attributes=_json_safe(snapshot.attributes or {}),
    )


def record_transition(db: Session, transition: EventTransition) -> EventRecordResult:
    """Persist one transition idempotently and return the stored event.

    Raises :class:`UnknownCamera` when the event's camera does not exist.
    """
    snapshot = transition.event
    camera = cameras_repo.get_by_id(db, snapshot.camera_id)
    if camera is None:
        raise UnknownCamera(f"unknown camera_id {snapshot.camera_id}")

    message = render_event(snapshot, camera_name=camera.name)
    existing = events_repo.get_by_event_id(db, snapshot.event_id)

    if existing is None:
        event = Event(
            event_id=snapshot.event_id,
            camera_id=snapshot.camera_id,
            message=message,
            state_version=snapshot.state_version,
            attributes={},
            evidence_refs=[],
        )
        _apply_snapshot(event, snapshot, message=message)
        db.add(event)
        try:
            db.flush()
        except IntegrityError:
            # Lost a race with another delivery of the same opening transition.
            db.rollback()
            raced = events_repo.get_by_event_id(db, snapshot.event_id)
            if raced is None:  # pragma: no cover - only if the row vanished concurrently
                raise
            return EventRecordResult(event=raced, applied=False)
        events_repo.add_transition(db, _transition_record(event.id, transition, message=message))
        db.commit()
        db.refresh(event)
        return EventRecordResult(event=event, applied=True)

    # Duplicate / out-of-order delivery: never move the revision backwards.
    if snapshot.state_version <= existing.state_version:
        return EventRecordResult(event=existing, applied=False)

    # Terminal events are immutable; a later recurrence is a new event (D-37).
    if existing.status in TERMINAL_STATUSES:
        return EventRecordResult(event=existing, applied=False)

    _apply_snapshot(existing, snapshot, message=message)
    events_repo.add_transition(db, _transition_record(existing.id, transition, message=message))
    try:
        db.commit()
    except IntegrityError:
        # Another delivery already appended this revision; keep the stored state.
        db.rollback()
        current = events_repo.get_by_event_id(db, snapshot.event_id)
        return EventRecordResult(event=current or existing, applied=False)
    db.refresh(existing)
    return EventRecordResult(event=existing, applied=True)


def get_event_by_id(db: Session, event_pk: int) -> Event | None:
    """Return a stored event by its internal primary key."""
    return events_repo.get_by_id(db, event_pk)
