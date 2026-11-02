"""Shared event contract, lifecycle, and rule configuration (Phase 5).

The vision worker imports these modules (it already imports ``app.config`` and
``app.models``), so the canonical event types, lifecycle states, and camera-rule
configuration have a single source of truth across the worker and the backend.

Nothing here writes to the database or renders text; persistence is Phase 6 and
deterministic rendering lives in :mod:`app.event_messages`.
"""

from app.events.lifecycle import (
    InvalidEventTransition,
    can_transition,
    transition,
)
from app.events.types import (
    Certainty,
    EventAction,
    EventSeverity,
    EventSnapshot,
    EventStatus,
    EventTransition,
    EventType,
    ReviewStatus,
)
from app.events.zones import (
    ALLOWED_ROTATIONS,
    BoundaryLine,
    BoundarySide,
    CameraRulesConfig,
    CameraRulesError,
    EventThresholds,
    Point,
    Zone,
    ZoneKind,
    parse_camera_rules,
    parse_rotation,
    validate_camera_configuration,
)

__all__ = [
    "ALLOWED_ROTATIONS",
    "BoundaryLine",
    "BoundarySide",
    "CameraRulesConfig",
    "CameraRulesError",
    "Certainty",
    "EventAction",
    "EventSeverity",
    "EventSnapshot",
    "EventStatus",
    "EventThresholds",
    "EventTransition",
    "EventType",
    "InvalidEventTransition",
    "Point",
    "ReviewStatus",
    "Zone",
    "ZoneKind",
    "can_transition",
    "parse_camera_rules",
    "parse_rotation",
    "transition",
    "validate_camera_configuration",
]
