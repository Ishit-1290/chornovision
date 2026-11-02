"""Temporal event engine orchestration tests (Phase 5)."""

from __future__ import annotations

import pytest
from app.events.types import EventType
from app.events.zones import CameraRulesConfig, parse_camera_rules

from vision.event_engine import (
    BaseRule,
    EngineFrame,
    EventIdFactory,
    TemporalEventEngine,
    build_engine,
)
from vision.event_engine.rules.boundary import BoundaryCrossingRule
from vision.event_engine.rules.motionless import MotionlessRule

from .event_helpers import (
    FULL_POLYGON,
    CollectingSink,
    at,
    make_frame,
    person,
)

INSIDE = (45.0, 40.0, 55.0, 60.0)
OUTSIDE = (45.0, 20.0, 55.0, 40.0)


def _entrance_configuration() -> dict:
    return {
        "zones": [
            {
                "id": "entrance",
                "name": "Main Entrance",
                "kind": "entrance",
                "polygon": FULL_POLYGON,
                "boundary": {
                    "p1": {"x": 0.0, "y": 0.5},
                    "p2": {"x": 1.0, "y": 0.5},
                    "inside_side": "left",
                },
            },
            {
                "id": "room",
                "name": "Living Room",
                "kind": "room",
                "polygon": FULL_POLYGON,
            },
        ],
        "event_rules": {
            "entrance_zone_id": "entrance",
            "room_zone_id": "room",
            "thresholds": {"boundary_confirm_frames": 1, "boundary_cooldown_seconds": 0.0},
        },
    }


def _all_activities_configuration() -> dict:
    configuration = _entrance_configuration()
    configuration["zones"].extend(
        [
            {"id": "door", "name": "Door", "kind": "door", "polygon": FULL_POLYGON},
            {
                "id": "porch",
                "name": "Porch",
                "kind": "package_area",
                "polygon": FULL_POLYGON,
            },
            {"id": "bed", "name": "Bed", "kind": "bed", "polygon": FULL_POLYGON},
            {"id": "floor", "name": "Floor", "kind": "floor", "polygon": FULL_POLYGON},
        ]
    )
    configuration["event_rules"].update(
        {
            "door_zone_id": "door",
            "package_zone_id": "porch",
            "bed_zone_id": "bed",
            "floor_zone_id": "floor",
        }
    )
    return configuration


class _BoomRule(BaseRule):
    event_types = ()

    def observe(self, frame: EngineFrame):
        raise RuntimeError("boom")


def test_only_configured_activities_are_built() -> None:
    engine = build_engine(1, _entrance_configuration())

    assert set(engine.event_types) == {
        EventType.PERSON_ENTERING,
        EventType.PERSON_LEAVING,
        EventType.ROOM_OCCUPANCY_CHANGE,
        EventType.CROWD_FORMING,
        EventType.PERSON_MOTIONLESS,
    }


def test_empty_configuration_enables_only_motionlessness() -> None:
    engine = build_engine(1, {})

    assert engine.event_types == (EventType.PERSON_MOTIONLESS,)


def test_all_eight_event_types_can_be_configured() -> None:
    engine = build_engine(1, _all_activities_configuration())

    assert set(engine.event_types) == set(EventType)


def test_engine_publishes_and_returns_the_same_transitions() -> None:
    sink = CollectingSink()
    engine = build_engine(1, _entrance_configuration(), event_sink=sink)

    engine.observe(make_frame(0.0, tracks=(person(bbox=OUTSIDE),)))
    returned = engine.observe(make_frame(1.0, tracks=(person(bbox=INSIDE),)))

    assert len(returned) == 2
    assert sink.transitions == returned
    assert sink.event_types == ["person_entering", "person_entering"]
    assert sink.statuses == ["active", "completed"]


def test_reset_clears_state_and_reproduces_ids_deterministically() -> None:
    sink = CollectingSink()
    engine = build_engine(1, _entrance_configuration(), event_sink=sink)
    frames = [
        make_frame(0.0, tracks=(person(bbox=OUTSIDE),)),
        make_frame(1.0, tracks=(person(bbox=INSIDE),)),
    ]

    first = [t for frame in frames for t in engine.observe(frame)]
    engine.reset()
    # After reset the same ordered input must look like a fresh session.
    second = [t for frame in frames for t in engine.observe(frame)]

    assert [t.event.model_dump() for t in first] == [t.event.model_dump() for t in second]


def test_a_failing_rule_does_not_stop_the_others() -> None:
    config = parse_camera_rules(_entrance_configuration())
    ids = EventIdFactory(1)
    boundary = BoundaryCrossingRule(camera_id=1, config=config, id_factory=ids)
    engine = TemporalEventEngine(
        camera_id=1,
        config=config,
        rules=[_BoomRule(camera_id=1, config=config, id_factory=ids), boundary],
        event_sink=CollectingSink(),
    )

    engine.observe(make_frame(0.0, tracks=(person(bbox=OUTSIDE),)))
    transitions = engine.observe(make_frame(1.0, tracks=(person(bbox=INSIDE),)))

    assert [t.event.event_type.value for t in transitions] == [
        "person_entering",
        "person_entering",
    ]
    assert engine.error_count == 2


def test_frame_from_another_camera_is_rejected() -> None:
    engine = build_engine(1, {})

    frame = EngineFrame(
        camera_id=2,
        monotonic=0.0,
        observed_at=at(0.0),
        frame_width=100,
        frame_height=100,
    )

    with pytest.raises(ValueError):
        engine.observe(frame)


def test_stream_end_finalises_open_events_through_the_sink() -> None:
    configuration = {
        "zones": [{"id": "room", "name": "Room", "kind": "room", "polygon": FULL_POLYGON}],
        "event_rules": {
            "room_zone_id": "room",
            "thresholds": {
                "occupancy_persistence_seconds": 1000.0,
                "crowd_occupancy_threshold": 1,
                "crowd_persistence_seconds": 0.0,
            },
        },
    }
    sink = CollectingSink()
    engine = build_engine(1, configuration, event_sink=sink)
    engine.observe(make_frame(0.0, tracks=(person(),)))
    engine.observe(make_frame(1.0, tracks=(person(),)))

    engine.on_stream_end(monotonic=2.0, observed_at=at(2.0), reason="stream_ended")

    assert sink.transitions[-1].event.status.value == "uncertain"
    assert sink.transitions[-1].event.attributes["completion_reason"] == "stream_ended"


def test_engine_can_be_constructed_with_a_motionless_rule_only() -> None:
    config = CameraRulesConfig()
    engine = TemporalEventEngine(
        camera_id=1,
        config=config,
        rules=[MotionlessRule(camera_id=1, config=config, id_factory=EventIdFactory(1))],
    )

    assert engine.event_types == (EventType.PERSON_MOTIONLESS,)
