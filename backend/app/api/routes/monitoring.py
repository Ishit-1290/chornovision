"""Monitoring control endpoints (FR-47, W §10).

These endpoints control the analysis runtime, not the browser viewer. They require
authentication; the start/pause/stop commands require a valid CSRF token.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_auth_context, get_csrf_auth_context
from app.db import get_db
from app.repositories import audit as audit_repo
from app.schemas.monitoring import MonitoringCommandResponse, MonitoringStatusResponse
from app.services import monitoring_service
from app.services.event_broadcaster import get_event_broadcaster

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])


def _command(name: str, function, db: Session, auth: AuthContext) -> MonitoringCommandResponse:
    try:
        result = function(db)
    except monitoring_service.InvalidMonitoringTransition as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    audit_repo.record(
        db,
        action=f"monitoring_{name}",
        user_id=auth.user.id,
        resource_type="monitoring",
        metadata={"state": result.state.value, "affected": result.affected},
    )
    get_event_broadcaster().publish(
        {
            "type": "monitoring",
            "state": result.state.value,
            "affected": result.affected,
        }
    )
    return MonitoringCommandResponse(state=result.state.value, affected=result.affected)


@router.post("/start", response_model=MonitoringCommandResponse)
def start(
    auth: AuthContext = Depends(get_csrf_auth_context),
    db: Session = Depends(get_db),
) -> MonitoringCommandResponse:
    """Start (or resume) monitoring; enabled cameras move to ``connecting``."""
    return _command("started", monitoring_service.start_monitoring, db, auth)


@router.post("/pause", response_model=MonitoringCommandResponse)
def pause(
    auth: AuthContext = Depends(get_csrf_auth_context),
    db: Session = Depends(get_db),
) -> MonitoringCommandResponse:
    """Pause monitoring; active cameras are stopped but keep their configuration."""
    return _command("paused", monitoring_service.pause_monitoring, db, auth)


@router.post("/stop", response_model=MonitoringCommandResponse)
def stop(
    auth: AuthContext = Depends(get_csrf_auth_context),
    db: Session = Depends(get_db),
) -> MonitoringCommandResponse:
    """Stop monitoring; every processing camera is stopped."""
    return _command("stopped", monitoring_service.stop_monitoring, db, auth)


@router.get("/status", response_model=MonitoringStatusResponse)
def monitoring_status(
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> MonitoringStatusResponse:
    """Report the global monitoring state and each camera's lifecycle state."""
    return monitoring_service.monitoring_snapshot(db)
