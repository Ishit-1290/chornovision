"""Shared rule/event machinery.

Each camera owns one instance of every configured rule. A rule holds bounded state for
its own activity and emits :class:`~app.events.types.EventTransition` objects. The
engine (not an individual rule) publishes transitions to the configured sink.

Event identity is stable for identical ordered input: it is a UUIDv5 derived from the
camera id, event type, zone, track, occurrence start time, and a deterministic
per-camera sequence number. ``state_version`` increments once per transition so the
Phase 6 handoff can reject stale submissions.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.events.lifecycle import can_transition, transition
from app.events.types import (
    Certainty,
    EventAction,
    EventSeverity,
    EventSnapshot,
    EventStatus,
    EventTransition,
    EventType,
    ensure_utc,
)
from app.events.zones import CameraRulesConfig

from vision.event_engine.types import EngineFrame, EntityObservation

#: Fixed namespace so event ids are reproducible across processes and test runs.
EVENT_NAMESPACE = uuid.UUID("0f0c2a5e-7b4d-4e1a-9c6f-2d8b5a3e1c70")

#: Bumped when rule semantics change; stored with every event (NFR-12).
RULE_VERSION = "phase5-v1"

#: Deterministic default presentation priorities (documented proposal, not medical).
SEVERITY_BY_EVENT: dict[EventType, EventSeverity] = {
    EventType.PERSON_ENTERING: EventSeverity.INFO,
    EventType.PERSON_LEAVING: EventSeverity.INFO,
    EventType.ROOM_OCCUPANCY_CHANGE: EventSeverity.INFO,
    EventType.CROWD_FORMING: EventSeverity.WARNING,
    EventType.DOOR_OPEN_TOO_LONG: EventSeverity.WARNING,
    EventType.PACKAGE_LEFT_AT_ENTRANCE: EventSeverity.WARNING,
    EventType.PERSON_MOTIONLESS: EventSeverity.WARNING,
    EventType.FALL_FROM_BED: EventSeverity.CRITICAL,
}


def confidence_from_tracks(tracks: list[EntityObservation]) -> float | None:
    """Return the minimum detector confidence, or ``None`` when unavailable.

    Phase 4 trackers may report ``0.0`` when they do not carry a confidence; that is
    not a real model output, so it is treated as unavailable rather than fabricated.
    """
    values = [float(track.confidence) for track in tracks if 0.0 < float(track.confidence) <= 1.0]
    return min(values) if values else None


def certainty_from_confidence(confidence: float | None) -> Certainty:
    """Map a documented confidence onto a categorical uncertainty level.

    The cut-offs are deterministic defaults (recorded in ``docs/DECISIONS.md``), not
    calibrated probabilities. When there is no reliable confidence the result is
    ``unknown`` rather than an invented number (FR-28).
    """
    if confidence is None:
        return Certainty.UNKNOWN
    if confidence >= 0.6:
        return Certainty.HIGH
    if confidence >= 0.35:
        return Certainty.MEDIUM
    return Certainty.LOW


class EventIdFactory:
    """Deterministic per-camera event id sequence."""

    def __init__(self, camera_id: int) -> None:
        self._camera_id = camera_id
        self._sequence = 0

    def reset(self) -> None:
        """Restart the per-camera sequence (new session, deterministic ids)."""
        self._sequence = 0

    def new(
        self,
        event_type: EventType,
        *,
        zone_id: str | None,
        entity_id: int | None,
        start_time: datetime,
    ) -> str:
        self._sequence += 1
        name = "|".join(
            (
                "chronovision",
                str(self._camera_id),
                event_type.value,
                zone_id or "-",
                "-" if entity_id is None else str(entity_id),
                ensure_utc(start_time).isoformat(),
                str(self._sequence),
            )
        )
        return str(uuid.uuid5(EVENT_NAMESPACE, name))


@dataclass
class ActiveEvent:
    """Mutable lifecycle state for one open event."""

    event_id: str
    camera_id: int
    event_type: EventType
    entity_id: int | None
    zone_id: str | None
    zone_name: str | None
    start_time: datetime
    trigger_time: datetime
    last_updated_at: datetime
    status: EventStatus
    severity: EventSeverity
    certainty: Certainty
    confidence: float | None
    attributes: dict[str, Any] = field(default_factory=dict)
    end_time: datetime | None = None
    state_version: int = 1
    evidence_refs: list[str] = field(default_factory=list)

    def snapshot(self) -> EventSnapshot:
        return EventSnapshot(
            event_id=self.event_id,
            camera_id=self.camera_id,
            event_type=self.event_type,
            entity_id=self.entity_id,
            zone_id=self.zone_id,
            zone_name=self.zone_name,
            start_time=self.start_time,
            trigger_time=self.trigger_time,
            last_updated_at=self.last_updated_at,
            end_time=self.end_time,
            status=self.status,
            severity=self.severity,
            state_version=self.state_version,
            confidence=self.confidence,
            certainty=self.certainty,
            attributes=dict(self.attributes),
            evidence_refs=list(self.evidence_refs),
        )


class BaseRule:
    """Base class for one activity rule on one camera."""

    event_types: tuple[EventType, ...] = ()

    def __init__(
        self,
        *,
        camera_id: int,
        config: CameraRulesConfig,
        id_factory: EventIdFactory,
    ) -> None:
        self.camera_id = camera_id
        self.config = config
        self.thresholds = config.thresholds
        self._ids = id_factory

    # -- rule interface --------------------------------------------------------
    def observe(self, frame: EngineFrame) -> list[EventTransition]:
        raise NotImplementedError

    def on_stream_end(
        self, *, monotonic: float, observed_at: datetime, reason: str
    ) -> list[EventTransition]:
        """Finalise open events when a session ends. Default: no persistent state."""
        return []

    def reset(self) -> None:
        """Clear all temporal state (called on every new connection and test reset)."""

    # -- event helpers ---------------------------------------------------------
    def _open(
        self,
        event_type: EventType,
        *,
        start_time: datetime,
        trigger_time: datetime,
        zone_id: str | None,
        zone_name: str | None,
        entity_id: int | None = None,
        status: EventStatus = EventStatus.ACTIVE,
        certainty: Certainty = Certainty.UNKNOWN,
        confidence: float | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> tuple[ActiveEvent, EventTransition]:
        if event_type not in self.event_types:  # pragma: no cover - programming error
            raise ValueError(f"{type(self).__name__} cannot emit {event_type.value}")
        start = ensure_utc(start_time)
        trigger = ensure_utc(trigger_time)
        active = ActiveEvent(
            event_id=self._ids.new(
                event_type,
                zone_id=zone_id,
                entity_id=entity_id,
                start_time=start,
            ),
            camera_id=self.camera_id,
            event_type=event_type,
            entity_id=entity_id,
            zone_id=zone_id,
            zone_name=zone_name,
            start_time=start,
            trigger_time=trigger,
            last_updated_at=trigger,
            status=status,
            severity=SEVERITY_BY_EVENT[event_type],
            certainty=certainty,
            confidence=confidence,
            attributes=self._base_attributes(attributes),
        )
        return active, EventTransition(action=EventAction.OPENED, event=active.snapshot())

    def _emit(
        self,
        active: ActiveEvent,
        *,
        action: EventAction,
        status: EventStatus,
        at: datetime,
        end_time: datetime | None = None,
        attributes: dict[str, Any] | None = None,
        confidence: float | None = None,
        certainty: Certainty | None = None,
    ) -> EventTransition:
        at = ensure_utc(at)
        if status is not active.status and not can_transition(active.status, status):
            transition(active.status, status)  # raises InvalidEventTransition
        active.status = status
        active.last_updated_at = at
        if end_time is not None:
            active.end_time = ensure_utc(end_time)
        if attributes:
            active.attributes.update(attributes)
        if confidence is not None:
            active.confidence = confidence
        if certainty is not None:
            active.certainty = certainty
        active.state_version += 1
        return EventTransition(action=action, event=active.snapshot())

    def _update(
        self,
        active: ActiveEvent,
        at: datetime,
        *,
        attributes: dict[str, Any] | None = None,
        confidence: float | None = None,
        certainty: Certainty | None = None,
    ) -> EventTransition:
        return self._emit(
            active,
            action=EventAction.UPDATED,
            status=active.status,
            at=at,
            attributes=attributes,
            confidence=confidence,
            certainty=certainty,
        )

    def _resolve(
        self,
        active: ActiveEvent,
        at: datetime,
        *,
        reason: str,
        attributes: dict[str, Any] | None = None,
    ) -> EventTransition:
        payload = {"completion_reason": reason}
        if attributes:
            payload.update(attributes)
        return self._emit(
            active,
            action=EventAction.RESOLVED,
            status=EventStatus.COMPLETED,
            at=at,
            end_time=at,
            attributes=payload,
        )

    def _cancel(self, active: ActiveEvent, at: datetime, *, reason: str) -> EventTransition:
        return self._emit(
            active,
            action=EventAction.CANCELLED,
            status=EventStatus.CANCELLED,
            at=at,
            end_time=at,
            attributes={"completion_reason": reason},
        )

    def _mark_uncertain(
        self,
        active: ActiveEvent,
        at: datetime,
        *,
        reason: str,
        end_time: datetime | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> EventTransition:
        payload = {"completion_reason": reason}
        if attributes:
            payload.update(attributes)
        if active.status is EventStatus.UNCERTAIN:
            return self._emit(
                active,
                action=EventAction.UPDATED,
                status=EventStatus.UNCERTAIN,
                at=at,
                end_time=end_time,
                attributes=payload,
            )
        return self._emit(
            active,
            action=EventAction.MARKED_UNCERTAIN,
            status=EventStatus.UNCERTAIN,
            at=at,
            end_time=end_time,
            attributes=payload,
        )

    def _finalise_on_stream_end(
        self,
        active: ActiveEvent,
        *,
        observed_at: datetime,
        reason: str,
    ) -> EventTransition | None:
        if active.status in (EventStatus.COMPLETED, EventStatus.CANCELLED):
            return None
        return self._mark_uncertain(
            active,
            observed_at,
            reason=reason,
            end_time=observed_at,
        )

    def _base_attributes(self, extra: dict[str, Any] | None) -> dict[str, Any]:
        attributes: dict[str, Any] = {
            "rule_version": RULE_VERSION,
            "config_version": self.config.config_version,
        }
        if extra:
            attributes.update(extra)
        return attributes
