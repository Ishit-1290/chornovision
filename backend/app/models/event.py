"""Persisted event and event-history models (Phase 6; FR-40, FR-45).

The ``events`` row holds the **current state** of one event; the ``event_transitions``
rows preserve the **history** of meaningful lifecycle transitions, so the two are never
conflated (``../guidelines.md`` §5.8, FR-21). The canonical shape and identifiers come
from :mod:`app.events.types` (D-10, D-34); this module only adds persistence columns.

Design notes:

* ``event_id`` is the deterministic UUIDv5 string produced by the event engine and carries
  a **unique** constraint, which makes the worker→backend handoff idempotent by identity
  (OQ-09/D-12).
* ``state_version`` is the per-event monotonic revision; a submission whose version is not
  newer than the stored one is rejected as stale (never overwrites newer state).
* ``message`` stores the **rendered** deterministic message at the time of the transition.
  It is never regenerated when a template changes (W §8).
* ``attributes`` keeps activity-specific metadata (including ``rule_version`` and
  ``config_version``) as JSON, separate from the display text (FR-33).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.utils import utcnow

if TYPE_CHECKING:
    from app.models.camera import Camera
    from app.models.evidence import Evidence


class Event(Base):
    """The current state of one persisted event."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Deterministic engine identity; unique so upserts are idempotent (D-12).
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    camera_id: Mapped[int] = mapped_column(
        ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zone_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    zone_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trigger_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    certainty: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Monotonic per-event revision used to reject stale out-of-order submissions.
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: The rendered deterministic message stored with the event (W §6, W §8).
    message: Mapped[str] = mapped_column(Text, nullable=False)
    attributes: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    review_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unreviewed", server_default="unreviewed"
    )
    #: Convenience copies of the versions carried in ``attributes`` (FR-45/NFR-12).
    rule_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    config_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
    )

    camera: Mapped[Camera] = relationship()
    transitions: Mapped[list[EventTransitionRecord]] = relationship(
        back_populates="event", cascade="all, delete-orphan", order_by="EventTransitionRecord.id"
    )
    evidence: Mapped[list[Evidence]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class EventTransitionRecord(Base):
    """One persisted lifecycle transition (immutable history row)."""

    __tablename__ = "event_transitions"
    __table_args__ = (UniqueConstraint("event_id", "state_version", name="uq_event_state_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Internal integer id of the owning event (not the public deterministic id).
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    state_version: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    certainty: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    attributes: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )

    event: Mapped[Event] = relationship(back_populates="transitions")
