"""Evidence metadata model (Phase 6; FR-38, FR-41, FR-42).

Evidence **bytes** live on the local filesystem under ``EVIDENCE_DIR``; this table stores
only metadata and a **relative** path (W §6). The authorized evidence endpoint resolves
that path inside the configured directory and rejects anything that escapes it (SEC-08).

An evidence row can exist before its file is finalized (``status='pending'``), become
available, or record an explicit capture failure (``status='failed'``) so that the event
stays visible with an unambiguous evidence status (FR-39).

``retention_status`` distinguishes live evidence (``retained``) from evidence that a
reviewer has pinned (``protected`` — never evicted) and evidence removed by retention
(``deleted``, kept for traceability; the file is gone but the row remains).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.utils import utcnow

if TYPE_CHECKING:
    from app.models.event import Event


class EvidenceMediaType(StrEnum):
    """The kinds of evidence the pipeline captures (FR-36)."""

    SNAPSHOT = "snapshot"
    CLIP = "clip"


class EvidenceStatus(StrEnum):
    """Capture outcome for one evidence item (FR-39)."""

    PENDING = "pending"
    AVAILABLE = "available"
    FAILED = "failed"


class RetentionStatus(StrEnum):
    """Retention lifecycle for one evidence item (FR-42)."""

    #: Live, eligible for time/size-based eviction.
    RETAINED = "retained"
    #: Pinned (for example during an active review) and never evicted.
    PROTECTED = "protected"
    #: Removed by retention; the row is kept for traceability, the file is gone.
    DELETED = "deleted"


class Evidence(Base):
    """Metadata for one snapshot or clip produced for an event."""

    __tablename__ = "evidence"
    __table_args__ = (
        # Registration is idempotent per (event, media type) — a retried handoff updates
        # the existing row instead of creating a duplicate (OQ-09/D-12).
        UniqueConstraint("event_id", "media_type", name="uq_evidence_event_media"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    media_type: Mapped[str] = mapped_column(String(16), nullable=False)
    #: Relative path under ``EVIDENCE_DIR`` (never absolute, never leaves the root).
    relative_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=EvidenceStatus.PENDING.value, server_default="pending"
    )
    retention_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=RetentionStatus.RETAINED.value,
        server_default="retained",
    )
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Short, non-sensitive reason when ``status='failed'`` (never a filesystem path).
    error: Mapped[str | None] = mapped_column(String(256), nullable=True)

    event: Mapped[Event] = relationship(back_populates="evidence")
