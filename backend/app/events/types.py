"""Canonical event contract shared by the vision engine and the backend (Phase 5).

The fields follow the event data contract in ``../guidelines.md`` §9 and
``../workflow_requirements.md`` §6/§8, with the canonical lowercase ``snake_case``
identifiers fixed by Decision D-10.

Design rules encoded here:

* ``start_time`` is the estimated beginning of the condition; ``trigger_time`` is when
  the rule's trigger condition was satisfied; ``last_updated_at`` is the most recent
  state update; ``end_time`` is set only when the condition ended. They are never
  substituted for one another (FR-20, FR-27).
* All persisted timestamps are timezone-aware and normalised to UTC. Rules still use a
  monotonic clock for elapsed durations, because wall-clock time can jump.
* ``confidence`` is only populated from a documented source (detector confidence or
  an explicit scoring procedure). When no reliable number exists, it stays ``None`` and
  the categorical :class:`Certainty` carries the uncertainty instead (FR-28).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.utils import ensure_utc


class EventType(StrEnum):
    """Canonical event identifiers (D-10). Two occupancy categories are retained
    because ``../guidelines.md`` §8.3 explicitly requires related but distinct types.
    """

    PERSON_ENTERING = "person_entering"
    PERSON_LEAVING = "person_leaving"
    ROOM_OCCUPANCY_CHANGE = "room_occupancy_change"
    CROWD_FORMING = "crowd_forming"
    DOOR_OPEN_TOO_LONG = "door_open_too_long"
    PACKAGE_LEFT_AT_ENTRANCE = "package_left_at_entrance"
    PERSON_MOTIONLESS = "person_motionless"
    FALL_FROM_BED = "fall_from_bed"


class EventStatus(StrEnum):
    """Lifecycle states required by ``../guidelines.md`` §7 and W §7 (FR-23)."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    COMPLETED = "completed"
    UNCERTAIN = "uncertain"
    CANCELLED = "cancelled"


class EventAction(StrEnum):
    """The lifecycle action that produced a transition.

    ``OPENED`` creates the event, ``UPDATED`` changes metadata or resumes from
    ``uncertain``, ``MARKED_UNCERTAIN`` records insufficient evidence, and
    ``RESOLVED``/``CANCELLED`` are terminal.
    """

    OPENED = "opened"
    UPDATED = "updated"
    MARKED_UNCERTAIN = "marked_uncertain"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class EventSeverity(StrEnum):
    """Presentation priority.

    These are deterministic defaults (documented as proposals, not source-mandated
    numbers). ``CRITICAL`` is a dashboard priority, never a medical classification.
    """

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class Certainty(StrEnum):
    """Categorical uncertainty used when a probability would be invented."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class ReviewStatus(StrEnum):
    """Human-review state. Phase 5 only creates the default; review is Phase 7."""

    UNREVIEWED = "unreviewed"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    CORRECTED = "corrected"


class EventSnapshot(BaseModel):
    """A point-in-time snapshot of one event, as produced by a rule transition."""

    model_config = ConfigDict(frozen=True)

    event_id: str = Field(min_length=1, max_length=64)
    camera_id: int = Field(ge=1)
    event_type: EventType
    entity_id: int | None = Field(default=None, ge=0)
    zone_id: str | None = Field(default=None, max_length=64)
    zone_name: str | None = Field(default=None, max_length=128)
    start_time: datetime
    trigger_time: datetime
    last_updated_at: datetime
    end_time: datetime | None = None
    status: EventStatus
    severity: EventSeverity
    #: Monotonic per-event revision used by the Phase 6 idempotent upsert to reject
    #: stale out-of-order submissions (OQ-09). It is deterministic for identical input.
    state_version: int = Field(default=1, ge=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    certainty: Certainty = Certainty.UNKNOWN
    attributes: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.UNREVIEWED

    @field_validator("start_time", "trigger_time", "last_updated_at", "end_time")
    @classmethod
    def _normalise_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else ensure_utc(value)

    @model_validator(mode="after")
    def _check_times(self) -> EventSnapshot:
        if self.trigger_time < self.start_time:
            raise ValueError("trigger_time must not precede start_time")
        if self.last_updated_at < self.start_time:
            raise ValueError("last_updated_at must not precede start_time")
        if self.end_time is not None:
            if self.end_time < self.start_time:
                raise ValueError("end_time must not precede start_time")
            if self.last_updated_at < self.end_time:
                raise ValueError("last_updated_at must not precede end_time")
        if self.status in (EventStatus.COMPLETED, EventStatus.CANCELLED):
            if self.end_time is None:
                raise ValueError(f"{self.status.value} events require end_time")
        elif self.end_time is not None and self.status in (
            EventStatus.CANDIDATE,
            EventStatus.ACTIVE,
        ):
            raise ValueError(f"{self.status.value} events must not have end_time")
        return self


class EventTransition(BaseModel):
    """One deterministic lifecycle transition emitted by the event engine."""

    model_config = ConfigDict(frozen=True)

    action: EventAction
    event: EventSnapshot

    @model_validator(mode="after")
    def _check_action(self) -> EventTransition:
        terminal = self.event.status in (EventStatus.COMPLETED, EventStatus.CANCELLED)
        if self.action is EventAction.RESOLVED and self.event.status is not EventStatus.COMPLETED:
            raise ValueError("resolved transitions must have status=completed")
        if self.action is EventAction.CANCELLED and self.event.status is not EventStatus.CANCELLED:
            raise ValueError("cancelled transitions must have status=cancelled")
        if self.action is EventAction.MARKED_UNCERTAIN and (
            self.event.status is not EventStatus.UNCERTAIN
        ):
            raise ValueError("marked_uncertain transitions must have status=uncertain")
        if self.action is EventAction.OPENED and terminal:
            raise ValueError("an opened transition must not be terminal")
        if self.action is EventAction.UPDATED and terminal:
            raise ValueError("an updated transition must not be terminal")
        return self
