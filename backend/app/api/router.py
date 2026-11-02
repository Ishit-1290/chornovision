"""Aggregate API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routes import (
    auth,
    cameras,
    events,
    evidence,
    health,
    internal,
    monitoring,
    realtime,
    settings,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(cameras.router)
api_router.include_router(monitoring.router)
api_router.include_router(events.router)
api_router.include_router(evidence.router)
api_router.include_router(settings.router)
api_router.include_router(realtime.router)
api_router.include_router(internal.router)

__all__ = ["api_router"]
