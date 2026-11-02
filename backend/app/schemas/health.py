"""Health/status schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Overall application health. Never includes secrets."""

    status: Literal["ok", "degraded"]
    app_name: str
    environment: str
    database: Literal["ok", "unavailable"]


class CameraHealthItem(BaseModel):
    """Minimal, non-sensitive per-camera health entry (no stream reference or config)."""

    id: int
    status: str


class CameraHealthResponse(BaseModel):
    """Camera health summary. Reports lifecycle states, never stream references."""

    count: int
    by_status: dict[str, int]
    cameras: list[CameraHealthItem]
