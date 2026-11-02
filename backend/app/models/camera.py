"""Camera configuration and lifecycle-state model.

A camera row holds the *configuration* (display name, stream reference, per-camera
options, enabled flag) plus the current *lifecycle state* (``status``). Stream
credentials are never stored: the stream-address validator rejects URLs containing
embedded userinfo (see ``app/services/stream_validation.py`` and Decision D-21).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, Boolean, DateTime, String, Text, func, true
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils import utcnow


class CameraStatus(StrEnum):
    """Per-camera lifecycle states (``../guidelines.md`` §6, FR-03).

    ``disconnected`` is a stream-health state and is deliberately **not** equivalent
    to "connected but no activity" (FR-05): a disconnected stream carries no frames at
    all, so entry/exit must never be inferred across such a period.
    """

    CONFIGURED = "configured"
    CONNECTING = "connecting"
    ACTIVE = "active"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"
    STOPPED = "stopped"
    FAILED = "failed"


class Camera(Base):
    """A registered camera and its current lifecycle state."""

    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True, unique=True)
    # Validated stream address (scheme + host + path + optional query). Never contains
    # embedded credentials. Responses expose a redacted form.
    stream_reference: Mapped[str] = mapped_column(String(2048), nullable=False)
    # Optional Fernet-encrypted ``{"username", "password"}`` JSON (Phase 10; D-64). Only the
    # internal gateway-registration path decrypts it; it is never returned or logged.
    stream_credentials_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CameraStatus.CONFIGURED.value,
        server_default=CameraStatus.CONFIGURED.value,
        index=True,
    )
    # Per-camera configuration (zones, thresholds, sampling policy, ...). Kept as JSON
    # so it can evolve without a migration; populated in later phases. There is no
    # database-level default: ``default=dict`` covers ORM inserts, and avoiding a
    # ``json`` server default keeps ``compare_server_default``-based drift detection
    # working (PostgreSQL has no equality operator for the ``json`` type).
    configuration: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
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
