"""Internal worker→backend endpoints (OQ-09, D-12).

These endpoints are consumed by the vision worker runtime, never by the browser. They are:

* hidden from the public OpenAPI schema;
* authenticated with the constant-time-compared ``X-Internal-Token`` even on localhost;
* free of per-request background tasks.

The worker is the authority on *runtime* health: it reports ``connecting``/``active``/
``degraded``/``disconnected``/``reconnecting``/``failed`` transitions, and the backend only
persists transitions that are legal in the per-camera lifecycle state machine (D-23). A
same-state report is an idempotent no-op that still refreshes the heartbeat; an illegal
transition is rejected with 409 and the current state, so the worker can resynchronise.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.auth.internal import require_internal_token
from app.db import get_db
from app.models.camera import CameraStatus
from app.repositories import cameras as cameras_repo
from app.schemas.internal import (
    InternalCamera,
    InternalEventResponse,
    InternalEventSubmission,
    InternalEvidenceResponse,
    InternalEvidenceSubmission,
    InternalPlanResponse,
    ReconcileResponse,
    WorkerStateReport,
    WorkerStateResponse,
)
from app.services import event_service, evidence_service, lifecycle, monitoring_service
from app.services.event_broadcaster import (
    camera_notification,
    event_notification,
    get_event_broadcaster,
)
from app.services.worker_registry import get_worker_registry

router = APIRouter(
    prefix="/api/internal",
    tags=["internal"],
    include_in_schema=False,
    dependencies=[Depends(require_internal_token)],
)


@router.get("/cameras", response_model=InternalPlanResponse)
def runtime_plan(db: Session = Depends(get_db)) -> InternalPlanResponse:
    """Return the requested monitoring state and each camera's configuration."""
    state = monitoring_service.get_monitoring_controller().state
    return InternalPlanResponse(
        monitoring_state=state.value,
        cameras=[
            InternalCamera(
                id=camera.id,
                name=camera.name,
                stream_reference=camera.stream_reference,
                enabled=camera.enabled,
                status=camera.status,
                configuration=dict(camera.configuration or {}),
            )
            for camera in cameras_repo.list_all(db)
        ],
    )


@router.post("/cameras/{camera_id}/state", response_model=WorkerStateResponse)
def report_camera_state(
    camera_id: int,
    payload: WorkerStateReport,
    db: Session = Depends(get_db),
):
    """Apply a worker-reported lifecycle transition and refresh the heartbeat."""
    camera = cameras_repo.get_by_id(db, camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")

    current = lifecycle.coerce_status(camera.status)
    target = lifecycle.coerce_status(payload.status)
    applied = False
    if target is not current:
        try:
            new_status = lifecycle.transition(current, target)
        except lifecycle.InvalidStateTransition:
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={
                    "detail": (f"illegal transition from {current.value!r} to {target.value!r}"),
                    "current_status": current.value,
                },
            )
        camera.status = new_status.value
        cameras_repo.save(db, camera)
        applied = True

    get_worker_registry().record(
        camera_id, target.value, detail=payload.detail, metrics=payload.metrics
    )
    if applied:
        get_event_broadcaster().publish(camera_notification(camera_id, target.value))
    return WorkerStateResponse(camera_id=camera_id, status=target.value, applied=applied)


@router.post("/reconcile", response_model=ReconcileResponse)
def reconcile(db: Session = Depends(get_db)) -> ReconcileResponse:
    """Reset cameras left in a processing state (worker startup reconciliation, D-24)."""
    affected = 0
    for camera in cameras_repo.list_by_statuses(db, set(lifecycle.PROCESSING_STATES)):
        camera.status = CameraStatus.STOPPED.value
        affected += 1
    if affected:
        db.commit()
    # A fresh worker owns the runtime now; drop any reports from the previous instance.
    get_worker_registry().clear()
    return ReconcileResponse(reconciled=affected)


@router.post("/events", response_model=InternalEventResponse)
def submit_event(
    payload: InternalEventSubmission,
    db: Session = Depends(get_db),
) -> InternalEventResponse:
    """Persist one worker event transition (idempotent by ``event_id``; D-12, FR-40)."""
    transition = _to_transition(payload)
    try:
        result = event_service.record_transition(db, transition)
    except event_service.UnknownCamera as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    event = result.event
    if result.applied:
        get_event_broadcaster().publish(event_notification(event))
    return InternalEventResponse(
        id=event.id,
        event_id=event.event_id,
        state_version=event.state_version,
        status=event.status,
        applied=result.applied,
    )


@router.post("/events/{event_id}/evidence", response_model=InternalEvidenceResponse)
def register_evidence(
    event_id: str,
    payload: InternalEvidenceSubmission,
    db: Session = Depends(get_db),
) -> InternalEvidenceResponse:
    """Register one snapshot/clip for an event (idempotent; FR-39, FR-41)."""
    if payload.event_id != event_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="event_id in the body does not match the path",
        )
    try:
        result = evidence_service.register_evidence(db, payload)
    except evidence_service.UnknownEvent as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except evidence_service.EvidenceServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    evidence = result.evidence
    if result.applied:
        get_event_broadcaster().publish(
            {
                "type": "evidence",
                "event_id": evidence.event_id,
                "evidence": {
                    "id": evidence.id,
                    "media_type": evidence.media_type,
                    "status": evidence.status,
                    "retention_status": evidence.retention_status,
                },
            }
        )
    return InternalEvidenceResponse(
        id=evidence.id,
        event_id=event_id,
        media_type=evidence.media_type,
        status=evidence.status,
        retention_status=evidence.retention_status,
        applied=result.applied,
    )


def _to_transition(payload: InternalEventSubmission):
    """Rebuild the canonical transition from the validated internal payload."""
    from app.events.types import EventTransition

    return EventTransition(action=payload.action, event=payload.event)
