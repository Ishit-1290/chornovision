"""Builders for canonical event snapshots/transitions used by Phase 6 tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.events.types import (
    Certainty,
    EventAction,
    EventSeverity,
    EventSnapshot,
    EventStatus,
    EventTransition,
    EventType,
)

START = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def snapshot(
    *,
    event_id: str = "11111111-1111-5111-8111-111111111111",
    camera_id: int = 1,
    event_type: EventType = EventType.PERSON_ENTERING,
    status: EventStatus = EventStatus.ACTIVE,
    state_version: int = 1,
    confidence: float | None = 0.8,
    certainty: Certainty = Certainty.MEDIUM,
    severity: EventSeverity = EventSeverity.INFO,
    offset_seconds: float = 0.0,
    last_updated_offset: float | None = None,
    end_offset_seconds: float | None = None,
    attributes: dict | None = None,
    zone_id: str | None = None,
    zone_name: str | None = None,
    entity_id: int | None = None,
) -> EventSnapshot:
    """Build a valid snapshot; offsets are relative to :data:`START`."""
    start = START + timedelta(seconds=offset_seconds)
    trigger = start
    last_updated = START + timedelta(
        seconds=last_updated_offset if last_updated_offset is not None else offset_seconds
    )
    end_time = None if end_offset_seconds is None else START + timedelta(seconds=end_offset_seconds)
    return EventSnapshot(
        event_id=event_id,
        camera_id=camera_id,
        event_type=event_type,
        status=status,
        state_version=state_version,
        confidence=confidence,
        certainty=certainty,
        severity=severity,
        start_time=start,
        trigger_time=trigger,
        last_updated_at=last_updated,
        end_time=end_time,
        attributes=dict(attributes or {"rule_version": "phase5-v1", "config_version": "v1"}),
        zone_id=zone_id,
        zone_name=zone_name,
        entity_id=entity_id,
    )


def opened(**overrides) -> EventTransition:
    overrides.setdefault("status", EventStatus.ACTIVE)
    return EventTransition(action=EventAction.OPENED, event=snapshot(**overrides))


def updated(**overrides) -> EventTransition:
    overrides.setdefault("status", EventStatus.ACTIVE)
    return EventTransition(action=EventAction.UPDATED, event=snapshot(**overrides))


def resolved(*, end_offset_seconds: float = 10.0, **overrides) -> EventTransition:
    overrides.setdefault("status", EventStatus.COMPLETED)
    overrides.setdefault("end_offset_seconds", end_offset_seconds)
    overrides.setdefault("last_updated_offset", end_offset_seconds)
    return EventTransition(action=EventAction.RESOLVED, event=snapshot(**overrides))


def cancelled(*, end_offset_seconds: float = 3.0, **overrides) -> EventTransition:
    overrides.setdefault("status", EventStatus.CANCELLED)
    overrides.setdefault("end_offset_seconds", end_offset_seconds)
    overrides.setdefault("last_updated_offset", end_offset_seconds)
    return EventTransition(action=EventAction.CANCELLED, event=snapshot(**overrides))


def uncertain(**overrides) -> EventTransition:
    overrides.setdefault("status", EventStatus.UNCERTAIN)
    return EventTransition(action=EventAction.MARKED_UNCERTAIN, event=snapshot(**overrides))
