"""Monitoring request/response schemas.

Monitoring is a single global control plane (``W`` §10) that drives each camera's
lifecycle state. It is deliberately separate from camera configuration.
"""

from __future__ import annotations

from pydantic import BaseModel


class MonitoringCameraState(BaseModel):
    """A camera's current lifecycle state as reported by the monitoring status endpoint."""

    id: int
    name: str
    enabled: bool
    status: str


class MonitoringStatusResponse(BaseModel):
    """Global monitoring state plus each camera's lifecycle state."""

    state: str
    running: bool
    counts: dict[str, int]
    cameras: list[MonitoringCameraState]


class MonitoringCommandResponse(BaseModel):
    """Result of a monitoring start/pause/stop command."""

    state: str
    affected: int
