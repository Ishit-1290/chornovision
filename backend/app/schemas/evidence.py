"""Evidence metadata response schemas (FR-41, FR-42).

The response exposes only metadata — never an absolute filesystem path. Bytes are fetched
through the authorized ``GET /api/evidence/{id}`` endpoint.

Phase 7 adds the reviewer-facing retention mutation (pin/unpin) that maps to the existing
``protected``/``retained`` retention states.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class EvidenceRetentionTarget(StrEnum):
    """The only reviewer-settable retention states.

    ``deleted`` is deliberately not settable through the API: deletion is an explicit,
    operator-driven retention action (D-43), never a dashboard side effect.
    """

    RETAINED = "retained"
    PROTECTED = "protected"


class EvidenceRetentionUpdate(BaseModel):
    """Body of ``PATCH /api/evidence/{id}``: pin or release one evidence item."""

    retention_status: EvidenceRetentionTarget


class EvidenceRead(BaseModel):
    """Public metadata for one evidence item."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: int
    media_type: str
    status: str
    retention_status: str
    relative_path: str | None
    file_size_bytes: int | None
    duration_seconds: float | None
    captured_at: datetime
    deleted_at: datetime | None
    error: str | None
