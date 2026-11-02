"""Read-only system-settings schema (Phase 7).

The dashboard's Settings page must never invent configuration. Retention and evidence
policy are environment-controlled and, by decision D-43, deletion is an explicit operator
action (``chronovision-admin prune-evidence``), not something the browser can change. This
endpoint therefore exposes the effective, **non-sensitive** operational policy so the UI can
display it honestly.
"""

from __future__ import annotations

from pydantic import BaseModel


class SystemSettingsResponse(BaseModel):
    """Effective non-sensitive operational settings plus evidence storage usage."""

    evidence_enabled: bool
    evidence_retention_days: int
    evidence_storage_limit_gb: int
    evidence_retention_on_register: bool
    evidence_rolling_buffer_seconds: int
    evidence_pre_event_seconds: int
    evidence_post_event_seconds: int
    evidence_snapshot_enabled: bool
    evidence_clip_fps: float
    evidence_clip_max_frames: int
    worker_heartbeat_timeout_seconds: int
    #: True when a streaming gateway is configured and live playback is explicitly enabled.
    live_playback_enabled: bool = False
    #: Sum of recorded evidence sizes for non-deleted items (never a filesystem path).
    evidence_storage_used_bytes: int
