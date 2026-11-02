"""Temporal event engine package (Phase 5).

The public surface used by the camera worker and the tests:

* :class:`~vision.event_engine.engine.TemporalEventEngine` /
  :func:`~vision.event_engine.engine.build_engine` — per-camera orchestration.
* :class:`~vision.event_engine.types.EngineFrame` — one processed frame's observations.
* :class:`~vision.event_engine.types.EventSink` /
  :class:`~vision.event_engine.types.NullEventSink` — the bounded handoff boundary.
* The rule classes, for direct unit testing.

Everything the rules emit is a canonical :class:`app.events.types.EventTransition`; the
worker never renders messages or writes to the database here.
"""

from __future__ import annotations

from vision.event_engine.base import (
    EVENT_NAMESPACE,
    RULE_VERSION,
    ActiveEvent,
    BaseRule,
    EventIdFactory,
    certainty_from_confidence,
    confidence_from_tracks,
)
from vision.event_engine.engine import TemporalEventEngine, build_engine
from vision.event_engine.rules import (
    BoundaryCrossingRule,
    DoorOpenRule,
    FallRule,
    MotionlessRule,
    OccupancyRule,
    PackageRule,
)
from vision.event_engine.types import (
    PERSON_CLASS,
    DoorState,
    DoorStateObservation,
    EngineFrame,
    EntityObservation,
    EventSink,
    NullEventSink,
    PoseObservation,
    Posture,
)

__all__ = [
    "EVENT_NAMESPACE",
    "PERSON_CLASS",
    "RULE_VERSION",
    "ActiveEvent",
    "BaseRule",
    "BoundaryCrossingRule",
    "DoorOpenRule",
    "DoorState",
    "DoorStateObservation",
    "EngineFrame",
    "EntityObservation",
    "EventIdFactory",
    "EventSink",
    "FallRule",
    "MotionlessRule",
    "NullEventSink",
    "OccupancyRule",
    "PackageRule",
    "PoseObservation",
    "Posture",
    "TemporalEventEngine",
    "build_engine",
    "certainty_from_confidence",
    "confidence_from_tracks",
]
