"""Shared builders for the Phase 5 event-engine tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.events.types import EventTransition
from app.events.zones import CameraRulesConfig, parse_camera_rules

from vision.event_engine.base import BaseRule, EventIdFactory
from vision.event_engine.types import (
    DoorStateObservation,
    EngineFrame,
    EntityObservation,
    PoseObservation,
)

START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

FULL_POLYGON = [
    {"x": 0.0, "y": 0.0},
    {"x": 1.0, "y": 0.0},
    {"x": 1.0, "y": 1.0},
    {"x": 0.0, "y": 1.0},
]


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def person(
    track_id: int = 1,
    *,
    bbox: tuple[float, float, float, float] = (45.0, 20.0, 55.0, 40.0),
    confidence: float = 0.9,
    class_name: str = "person",
) -> EntityObservation:
    return EntityObservation(
        track_id=track_id,
        class_name=class_name,
        confidence=confidence,
        bbox=bbox,
    )


def make_frame(
    monotonic: float,
    *,
    tracks: tuple[EntityObservation, ...] = (),
    width: int = 100,
    height: int = 100,
    observed_at: datetime | None = None,
    door_states: tuple[DoorStateObservation, ...] = (),
    poses: tuple[PoseObservation, ...] = (),
) -> EngineFrame:
    return EngineFrame(
        camera_id=1,
        monotonic=monotonic,
        observed_at=observed_at or at(monotonic),
        frame_width=width,
        frame_height=height,
        tracks=tracks,
        door_states=door_states,
        poses=poses,
    )


def build_rule(rule_cls: type[BaseRule], configuration: dict) -> BaseRule:
    config: CameraRulesConfig = parse_camera_rules(configuration)
    return rule_cls(camera_id=1, config=config, id_factory=EventIdFactory(1))


class CollectingSink:
    """Capture every transition published by the engine."""

    def __init__(self) -> None:
        self.transitions: list[EventTransition] = []

    def publish(self, transition: EventTransition) -> None:
        self.transitions.append(transition)

    @property
    def event_types(self) -> list[str]:
        return [transition.event.event_type.value for transition in self.transitions]

    @property
    def statuses(self) -> list[str]:
        return [transition.event.status.value for transition in self.transitions]
