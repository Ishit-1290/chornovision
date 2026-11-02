"""Pydantic request/response schemas."""

from app.schemas.auth import LoginRequest, LoginResponse, MessageResponse
from app.schemas.camera import CameraCreate, CameraRead, CameraUpdate
from app.schemas.event import (
    EventListItem,
    EventListResponse,
    EventRead,
    EventReviewUpdate,
    EventTransitionRead,
)
from app.schemas.evidence import (
    EvidenceRead,
    EvidenceRetentionTarget,
    EvidenceRetentionUpdate,
)
from app.schemas.health import CameraHealthItem, CameraHealthResponse, HealthResponse
from app.schemas.monitoring import (
    MonitoringCameraState,
    MonitoringCommandResponse,
    MonitoringStatusResponse,
)
from app.schemas.settings import SystemSettingsResponse
from app.schemas.user import UserRead

__all__ = [
    "CameraCreate",
    "CameraHealthItem",
    "CameraHealthResponse",
    "CameraRead",
    "CameraUpdate",
    "EventListItem",
    "EventListResponse",
    "EventRead",
    "EventReviewUpdate",
    "EventTransitionRead",
    "EvidenceRead",
    "EvidenceRetentionTarget",
    "EvidenceRetentionUpdate",
    "HealthResponse",
    "LoginRequest",
    "LoginResponse",
    "MessageResponse",
    "MonitoringCameraState",
    "MonitoringCommandResponse",
    "MonitoringStatusResponse",
    "SystemSettingsResponse",
    "UserRead",
]
