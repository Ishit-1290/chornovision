"""Audit log model.

Records security-relevant actions. Passwords, session tokens, and camera credentials
must never be written here.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.utils import utcnow


class AuditLog(Base):
    """A single audit record for an application action."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, server_default=func.now()
    )
    # ``metadata`` is reserved on the declarative class, so the attribute is renamed
    # while the database column keeps the documented name.
    log_metadata: Mapped[dict[str, object] | None] = mapped_column("metadata", JSON, nullable=True)
