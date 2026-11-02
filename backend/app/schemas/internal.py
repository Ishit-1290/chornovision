"""Schemas for the internal worker→backend channel (OQ-09, D-12).

These payloads are only reachable with the internal token. They carry no credentials: camera
stream references never embed userinfo (D-22), and the worker only reports lifecycle state
plus non-sensitive numeric metrics.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.events.types import EventAction, EventSnapshot
from app.models.camera import CameraStatus
from app.models.evidence import EvidenceMediaType, EvidenceStatus


class WorkerStateReport(BaseModel):
    """A lifecycle-state report (and heartbeat) from a camera worker."""

    status: str
    detail: str | None = Field(default=None, max_length=128)
    metrics: dict[str, float | int | str | None] | None = None

    @field_validator("status")
    @classmethod
    def _known_status(cls, value: str) -> str:
        try:
            return CameraStatus(value).value
        except ValueError as exc:
            raise ValueError(f"unknown camera status {value!r}") from exc


class WorkerStateResponse(BaseModel):
    """What the backend actually stored for the report."""

    camera_id: int
    status: str
    applied: bool


class InternalCamera(BaseModel):
    """A camera in the internal runtime plan (includes the full stream reference)."""

    id: int
    name: str
    stream_reference: str
    enabled: bool
    status: str
    configuration: dict[str, object] = Field(default_factory=dict)


class InternalPlanResponse(BaseModel):
    """The backend's requested runtime state, consumed by the worker supervisor."""

    monitoring_state: str
    cameras: list[InternalCamera]


class ReconcileResponse(BaseModel):
    """Result of resetting cameras left in a processing state."""

    reconciled: int


class InternalEventSubmission(BaseModel):
    """One event transition submitted by a worker (idempotent by ``event_id``; D-12).

    The body mirrors :class:`app.events.types.EventTransition` but forbids unknown keys, so
    a malformed or upgraded payload is rejected rather than silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    action: EventAction
    event: EventSnapshot

    @model_validator(mode="after")
    def _check_action_matches_status(self) -> InternalEventSubmission:
        # Reuse the canonical transition validation so the internal channel cannot accept a
        # combination the engine could never produce.
        from app.events.types import EventTransition

        EventTransition(action=self.action, event=self.event)
        return self


class InternalEventResponse(BaseModel):
    """The backend's record of an event submission."""

    id: int
    event_id: str
    state_version: int
    status: str
    #: ``False`` when the submission was a stale/duplicate no-op (idempotent delivery).
    applied: bool


class InternalEvidenceSubmission(BaseModel):
    """One snapshot/clip registration from a worker (D-12; FR-39, FR-41)."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=64)
    media_type: EvidenceMediaType
    status: EvidenceStatus
    #: Relative path *inside* ``EVIDENCE_DIR`` (validated again by the backend).
    relative_path: str | None = Field(default=None, max_length=1024)
    file_size_bytes: int | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0.0)
    captured_at: datetime
    #: A short, non-sensitive reason when ``status='failed'`` (never a filesystem path).
    error: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def _check_status_fields(self) -> InternalEvidenceSubmission:
        if self.status is EvidenceStatus.AVAILABLE and not self.relative_path:
            raise ValueError("status='available' requires relative_path")
        if self.status is EvidenceStatus.FAILED and not (self.error and self.error.strip()):
            raise ValueError("status='failed' requires error")
        return self


class InternalEvidenceResponse(BaseModel):
    """The backend's record of an evidence registration."""

    id: int
    event_id: str
    media_type: str
    status: str
    retention_status: str
    applied: bool
