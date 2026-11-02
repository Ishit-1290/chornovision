"""Health and system-status endpoints.

These endpoints are readable without authentication and must never expose secrets or
sensitive configuration. A database problem is reported as ``degraded`` rather than
failing the request, so operational tooling can still observe the process.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.repositories import cameras as cameras_repo
from app.schemas.health import CameraHealthItem, CameraHealthResponse, HealthResponse
from app.services import monitoring_service

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    """Report application and database availability."""
    settings = get_settings()
    database = "ok"
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        database = "unavailable"
    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        app_name=settings.app_name,
        environment=settings.environment.value,
        database=database,
    )


@router.get("/cameras", response_model=CameraHealthResponse)
def camera_health(db: Session = Depends(get_db)) -> CameraHealthResponse:
    """Per-camera lifecycle-state summary.

    Unauthenticated but deliberately non-sensitive: it reports ids and lifecycle states
    only, never stream references, names, or configuration. A database failure yields an
    empty summary instead of an error (consistent with ``/api/health``).
    """
    try:
        cameras = cameras_repo.list_all(db)
        projected = [(camera, monitoring_service.effective_status(camera)) for camera in cameras]
    except SQLAlchemyError:
        return CameraHealthResponse(count=0, by_status={}, cameras=[])
    by_status: dict[str, int] = {}
    for _camera, camera_status in projected:
        by_status[camera_status] = by_status.get(camera_status, 0) + 1
    return CameraHealthResponse(
        count=len(projected),
        by_status=by_status,
        cameras=[CameraHealthItem(id=camera.id, status=status) for camera, status in projected],
    )
