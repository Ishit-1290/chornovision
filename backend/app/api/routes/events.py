"""Event read and human-review endpoints (W §10, FR-26, FR-44).

The timeline supports filtering, ordering, and pagination; the detail view returns the stored
transitions and evidence metadata. Phase 7 adds the reviewer mutation (``PATCH``) that was
deferred from Phase 6 (OQ-10): a reviewer records a decision on ``review_status`` without
altering the original deterministic message, timestamps, or lifecycle state, so review stays
traceable (FR-44). Every endpoint requires an authenticated session; writes also require a
CSRF token. Responses never contain stream references or credentials.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_csrf_auth_context, get_current_user
from app.db import get_db
from app.events.types import EventStatus, EventType, ReviewStatus
from app.repositories import audit as audit_repo
from app.repositories import events as events_repo
from app.schemas.event import EventListItem, EventListResponse, EventRead, EventReviewUpdate
from app.services import event_service
from app.services.event_broadcaster import event_notification, get_event_broadcaster

router = APIRouter(
    prefix="/api/events",
    tags=["events"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=EventListResponse)
def list_events(
    camera_id: int | None = Query(default=None, ge=1),
    event_type: EventType | None = Query(default=None),
    status: EventStatus | None = Query(default=None),
    review_status: ReviewStatus | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    order: Literal["asc", "desc"] = Query(default="desc"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> EventListResponse:
    """List events with optional filters, ordering, and pagination."""
    filters = {
        "camera_id": camera_id,
        "event_type": event_type.value if event_type is not None else None,
        "status": status.value if status is not None else None,
        "review_status": review_status.value if review_status is not None else None,
        "since": since,
        "until": until,
    }
    rows = events_repo.list_events(db, limit=limit, offset=offset, order=order, **filters)
    total = events_repo.count_events(db, **filters)
    return EventListResponse(
        items=[EventListItem.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{event_pk}", response_model=EventRead)
def get_event(event_pk: int, db: Session = Depends(get_db)) -> EventRead:
    """Return one event with its transition history and evidence metadata."""
    event = event_service.get_event_by_id(db, event_pk)
    if event is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Event not found")
    return EventRead.model_validate(event)


@router.patch("/{event_pk}", response_model=EventRead)
def review_event(
    event_pk: int,
    payload: EventReviewUpdate,
    auth: AuthContext = Depends(get_csrf_auth_context),
    db: Session = Depends(get_db),
) -> EventRead:
    """Record a human-review decision on an event (FR-44; OQ-10).

    Only ``review_status`` changes. The stored deterministic message, event timestamps,
    confidence/certainty, and lifecycle state are untouched so the original model output
    stays intact and auditable.
    """
    event = event_service.get_event_by_id(db, event_pk)
    if event is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="Event not found")

    previous = event.review_status
    event.review_status = payload.review_status.value
    events_repo.save(db, event)

    audit_metadata: dict[str, object] = {"from": previous, "to": event.review_status}
    if payload.note:
        audit_metadata["note"] = payload.note
    audit_repo.record(
        db,
        action="event_reviewed",
        user_id=auth.user.id,
        resource_type="event",
        resource_id=str(event.id),
        metadata=audit_metadata,
    )
    get_event_broadcaster().publish(event_notification(event))
    return EventRead.model_validate(event)
