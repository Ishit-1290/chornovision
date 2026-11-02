"""ORM models.

Importing this package registers every model on ``Base.metadata`` so that Alembic
autogeneration and ``Base.metadata.create_all`` see the full schema.
"""

from app.models.audit_log import AuditLog
from app.models.auth_session import UserSession
from app.models.base import Base
from app.models.camera import Camera, CameraStatus
from app.models.event import Event, EventTransitionRecord
from app.models.evidence import Evidence, EvidenceMediaType, EvidenceStatus, RetentionStatus
from app.models.user import User

__all__ = [
    "AuditLog",
    "Base",
    "Camera",
    "CameraStatus",
    "Event",
    "EventTransitionRecord",
    "Evidence",
    "EvidenceMediaType",
    "EvidenceStatus",
    "RetentionStatus",
    "User",
    "UserSession",
]
