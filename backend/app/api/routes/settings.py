"""Read-only system settings for the dashboard (Phase 7).

Retention and evidence policy are environment-controlled (D-11/D-43); the API deliberately
does not let the browser mutate them. This endpoint gives the Settings page the effective,
non-sensitive values plus current evidence storage usage so the UI can display the truth
instead of hard-coding numbers. Authentication is required even though nothing here is
secret, keeping the settings surface consistent with the rest of the API.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.config import get_settings
from app.db import get_db
from app.repositories import evidence as evidence_repo
from app.schemas.settings import SystemSettingsResponse

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=SystemSettingsResponse)
def read_settings(db: Session = Depends(get_db)) -> SystemSettingsResponse:
    """Return the effective non-sensitive operational settings."""
    settings = get_settings()
    return SystemSettingsResponse(
        evidence_enabled=settings.evidence_enabled,
        evidence_retention_days=settings.evidence_retention_days,
        evidence_storage_limit_gb=settings.evidence_storage_limit_gb,
        evidence_retention_on_register=settings.evidence_retention_on_register,
        evidence_rolling_buffer_seconds=settings.evidence_rolling_buffer_seconds,
        evidence_pre_event_seconds=settings.evidence_pre_event_seconds,
        evidence_post_event_seconds=settings.evidence_post_event_seconds,
        evidence_snapshot_enabled=settings.evidence_snapshot_enabled,
        evidence_clip_fps=settings.evidence_clip_fps,
        evidence_clip_max_frames=settings.evidence_clip_max_frames,
        worker_heartbeat_timeout_seconds=settings.worker_heartbeat_timeout_seconds,
        live_playback_enabled=settings.live_playback_enabled,
        evidence_storage_used_bytes=evidence_repo.total_stored_bytes(db),
    )
