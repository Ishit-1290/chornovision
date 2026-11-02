"""Event response and review schemas (W §10, FR-26, FR-44).

Phase 6 delivered the read surface (list/detail with filters + pagination). Phase 7 adds the
human-review mutation (``PATCH /api/events/{id}``) that was deliberately deferred (OQ-10).
Responses never include stream references or credentials.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.events.types import ReviewStatus
from app.schemas.evidence import EvidenceRead


class EventTransitionRead(BaseModel):
    """One persisted lifecycle transition (history row)."""

    model_config = ConfigDict(from_attributes=True)

    state_version: int
    action: str
    status: str
    occurred_at: datetime
    end_time: datetime | None
    certainty: str
    confidence: float | None
    message: str


class EventListItem(BaseModel):
    """A compact event record for timeline listings."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: str
    camera_id: int
    event_type: str
    entity_id: int | None
    zone_id: str | None
    zone_name: str | None
    start_time: datetime
    trigger_time: datetime
    last_updated_at: datetime
    end_time: datetime | None
    status: str
    severity: str
    certainty: str
    confidence: float | None
    state_version: int
    message: str
    review_status: str


class EventRead(EventListItem):
    """A full event record including attributes, evidence refs, and evidence rows."""

    attributes: dict[str, object] = Field(default_factory=dict)
    evidence_refs: list[str] = Field(default_factory=list)
    rule_version: str | None = None
    config_version: str | None = None
    created_at: datetime
    updated_at: datetime
    evidence: list[EvidenceRead] = Field(default_factory=list)
    transitions: list[EventTransitionRead] = Field(default_factory=list)


class EventListResponse(BaseModel):
    """A paginated page of events."""

    items: list[EventListItem]
    total: int
    limit: int
    offset: int


class EventReviewUpdate(BaseModel):
    """Body of ``PATCH /api/events/{id}``: a human-review decision.

    Review decisions are stored on the event (``review_status``) separately from the
    original model output, preserving traceability (FR-44). They never rewrite the
    deterministic message, timestamps, confidence, or lifecycle state.
    """

    review_status: ReviewStatus
    #: Optional short reviewer note for the audit log. Never rendered into the message.
    note: str | None = Field(default=None, max_length=500)
