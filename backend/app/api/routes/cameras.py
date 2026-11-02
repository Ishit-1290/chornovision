"""Camera configuration endpoints (W §10).

All endpoints require authentication; state-changing endpoints additionally require a
valid CSRF token. Responses expose a redacted stream reference and never credentials.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_auth_context, get_csrf_auth_context
from app.db import get_db
from app.repositories import audit as audit_repo
from app.repositories import cameras as cameras_repo
from app.schemas.camera import CameraCreate, CameraRead, CameraUpdate
from app.schemas.live import LivePlaybackInfo
from app.services import camera_service, live_service
from app.services.event_broadcaster import camera_notification, get_event_broadcaster

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


def _get_camera_or_404(db: Session, camera_id: int):
    camera = cameras_repo.get_by_id(db, camera_id)
    if camera is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    return camera


@router.get("", response_model=list[CameraRead])
def list_cameras(
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> list[CameraRead]:
    """List every configured camera."""
    return [camera_service.to_read(camera) for camera in cameras_repo.list_all(db)]


@router.post("", response_model=CameraRead, status_code=status.HTTP_201_CREATED)
def create_camera(
    payload: CameraCreate,
    auth: AuthContext = Depends(get_csrf_auth_context),
    db: Session = Depends(get_db),
) -> CameraRead:
    """Register a new camera."""
    try:
        camera = camera_service.create_camera(
            db,
            name=payload.name,
            stream_reference=payload.stream_reference,
            enabled=payload.enabled,
            configuration=payload.configuration,
            stream_username=payload.stream_username,
            stream_password=payload.stream_password,
        )
    except camera_service.CameraNameConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except camera_service.InvalidStreamReference as exc:
        # The reason is safe to return; the raw reference is never echoed.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid stream reference: {exc}",
        ) from exc
    except camera_service.InvalidCameraConfiguration as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid camera configuration: {exc}",
        ) from exc

    audit_repo.record(
        db,
        action="camera_created",
        user_id=auth.user.id,
        resource_type="camera",
        resource_id=str(camera.id),
        metadata={"name": camera.name},
    )
    get_event_broadcaster().publish(camera_notification(camera.id, camera.status))
    # Best-effort gateway registration; never affects camera creation on gateway failure.
    live_service.on_camera_changed(camera)
    return camera_service.to_read(camera)


@router.get("/{camera_id}", response_model=CameraRead)
def get_camera(
    camera_id: int,
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> CameraRead:
    """Fetch a single camera by id."""
    return camera_service.to_read(_get_camera_or_404(db, camera_id))


@router.patch("/{camera_id}", response_model=CameraRead)
def update_camera(
    camera_id: int,
    payload: CameraUpdate,
    auth: AuthContext = Depends(get_csrf_auth_context),
    db: Session = Depends(get_db),
) -> CameraRead:
    """Update a camera's configuration. Omitted fields are unchanged."""
    camera = _get_camera_or_404(db, camera_id)
    changed = sorted(
        f
        for f in payload.model_fields_set
        if getattr(payload, f) is not None and f not in {"stream_username", "stream_password"}
    )
    if "stream_username" in payload.model_fields_set:
        changed = sorted({*changed, "stream_credentials"})
    if payload.clear_stream_credentials:
        changed = sorted({*changed, "stream_credentials"})
    try:
        camera = camera_service.update_camera(
            db,
            camera,
            name=payload.name,
            stream_reference=payload.stream_reference,
            enabled=payload.enabled,
            configuration=payload.configuration,
            stream_username=payload.stream_username,
            stream_password=payload.stream_password,
            clear_stream_credentials=payload.clear_stream_credentials,
        )
    except camera_service.CameraNameConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except camera_service.InvalidStreamReference as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid stream reference: {exc}",
        ) from exc
    except camera_service.InvalidCameraConfiguration as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid camera configuration: {exc}",
        ) from exc

    if changed:
        # Record field names only; never the (possibly sensitive) values.
        audit_repo.record(
            db,
            action="camera_updated",
            user_id=auth.user.id,
            resource_type="camera",
            resource_id=str(camera.id),
            metadata={"fields": changed},
        )
    get_event_broadcaster().publish(camera_notification(camera.id, camera.status))
    # Best-effort gateway refresh (re-register on source/credential change, remove on disable).
    live_service.on_camera_changed(camera)
    return camera_service.to_read(camera)


@router.get("/{camera_id}/live", response_model=LivePlaybackInfo)
def get_live_playback(
    camera_id: int,
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> LivePlaybackInfo:
    """Report live-playback availability for a camera (read-only).

    Returns only the gateway path and WHEP URL; camera sources and credentials are never
    exposed. A gateway outage degrades this endpoint alone.
    """
    return live_service.playback_status(_get_camera_or_404(db, camera_id))


@router.post("/{camera_id}/live/start", response_model=LivePlaybackInfo)
def start_live_playback(
    camera_id: int,
    auth: AuthContext = Depends(get_csrf_auth_context),
    db: Session = Depends(get_db),
) -> LivePlaybackInfo:
    """Reconcile the gateway path and return playback details.

    Idempotent and explicit: it never starts camera monitoring, and it is only meaningful
    when live playback is configured (otherwise it reports ``unavailable``).
    """
    return live_service.start_playback(_get_camera_or_404(db, camera_id))
