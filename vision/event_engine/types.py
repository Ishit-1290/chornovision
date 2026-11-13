"""Input/output types for the temporal event engine (Phase 5).

The engine consumes one :class:`EngineFrame` per processed video frame. It never
touches a decoder, detector, database, network, or HTTP handler; the worker adapts its
detector/tracker output into these plain values.

Detection classes are lower-case strings from the detector. Person rules use
``"person"``; package rules use the configurable set in
:mod:`vision.event_engine.rules.package`. Door state and pose are *separate optional
inputs*: if the current detector pipeline does not produce them, the corresponding
rules stay inactive instead of inventing observations.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from app.events.types import EventTransition, ensure_utc

PERSON_CLASS = "person"


@dataclass(frozen=True)
class EntityObservation:
    """A tracked entity on one frame (pixel bounding box)."""

    track_id: int
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]

    @property
    def normalised_class(self) -> str:
        return self.class_name.strip().lower()


class DoorState(StrEnum):
    """Observed door state. ``UNKNOWN`` tolerates brief classifier uncertainty."""

    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DoorStateObservation:
    """A door-state observation. No door-state producer is integrated yet."""

    state: DoorState
    zone_id: str | None = None
    confidence: float | None = None


class Posture(StrEnum):
    """Coarse posture used by the potential-fall rule."""

    UPRIGHT = "upright"
    SITTING = "sitting"
    LYING = "lying"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PoseObservation:
    """A pose/posture observation. No pose producer is integrated yet."""

    track_id: int
    posture: Posture
    height_ratio: float | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class EngineFrame:
    """Everything one rule pass may use for one camera frame."""

    camera_id: int
    monotonic: float
    observed_at: datetime
    frame_width: int
    frame_height: int
    tracks: Sequence[EntityObservation] = field(default_factory=tuple)
    door_states: Sequence[DoorStateObservation] = field(default_factory=tuple)
    poses: Sequence[PoseObservation] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.camera_id < 1:
            raise ValueError("camera_id must be >= 1")
        if self.monotonic < 0:
            raise ValueError("monotonic must be >= 0")
        if self.frame_width < 1 or self.frame_height < 1:
            raise ValueError("frame dimensions must be positive")
        object.__setattr__(self, "observed_at", ensure_utc(self.observed_at))
        object.__setattr__(self, "tracks", tuple(self.tracks))
        object.__setattr__(self, "door_states", tuple(self.door_states))
        object.__setattr__(self, "poses", tuple(self.poses))

    def person_tracks(self) -> list[EntityObservation]:
        """Return person tracks in their original order."""
        return [track for track in self.tracks if track.normalised_class == PERSON_CLASS]

    def tracks_of(self, class_names: Iterable[str]) -> list[EntityObservation]:
        wanted = {name.strip().lower() for name in class_names}
        return [track for track in self.tracks if track.normalised_class in wanted]

    def pose_for(self, track_id: int) -> PoseObservation | None:
        for pose in self.poses:
            if pose.track_id == track_id:
                return pose
        return None

    def door_state(self, zone_id: str | None) -> DoorStateObservation | None:
        if zone_id is None:
            return self.door_states[0] if self.door_states else None
        for observation in self.door_states:
            if observation.zone_id == zone_id:
                return observation
        return None


class EventSink(Protocol):
    """Receives deterministic lifecycle transitions.

    Implementations **must not block** the caller. Phase 6 will provide the bounded
    worker→backend handoff; Phase 5 uses :class:`NullEventSink` in production and a
    collecting sink in tests.
    """

    def publish(self, transition: EventTransition) -> None:
        """Publish one transition."""


class NullEventSink:
    """A sink that discards transitions (Phase 5 default; no persistence yet)."""

    def publish(self, transition: EventTransition) -> None:
        return None
