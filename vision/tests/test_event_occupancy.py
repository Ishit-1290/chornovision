"""Occupancy and crowd rule tests (EV-03; G §8.3)."""

from __future__ import annotations

from vision.event_engine.rules.occupancy import OccupancyRule

from .event_helpers import FULL_POLYGON, at, build_rule, make_frame, person


def _config(**thresholds: float) -> dict:
    return {
        "zones": [{"id": "room", "name": "Living Room", "kind": "room", "polygon": FULL_POLYGON}],
        "event_rules": {
            "room_zone_id": "room",
            "thresholds": thresholds,
        },
    }


def _people(count: int) -> tuple:
    return tuple(
        person(track_id=track_id, bbox=(10.0, 10.0, 20.0, 20.0)) for track_id in range(1, count + 1)
    )


def _of_type(transitions, event_type: str):
    return [t for t in transitions if t.event.event_type.value == event_type]


def test_occupancy_change_is_debounced_until_it_persists() -> None:
    rule = build_rule(OccupancyRule, _config(occupancy_persistence_seconds=2.0))

    assert rule.observe(make_frame(0.0, tracks=_people(1))) == []
    assert rule.observe(make_frame(1.0, tracks=_people(1))) == []
    transitions = rule.observe(make_frame(2.0, tracks=_people(1)))

    events = [t.event for t in _of_type(transitions, "room_occupancy_change")]
    assert len(events) == 2  # opened + resolved (instantaneous)
    assert events[0].status.value == "active"
    assert events[1].status.value == "completed"
    assert events[0].attributes["occupancy_count"] == 1
    assert events[0].attributes["previous_occupancy_count"] is None
    assert events[0].zone_name == "Living Room"


def test_temporary_detection_loss_does_not_flicker_occupancy() -> None:
    rule = build_rule(
        OccupancyRule,
        _config(
            occupancy_persistence_seconds=0.0,
            occupancy_retention_seconds=5.0,
        ),
    )

    first = rule.observe(make_frame(0.0, tracks=_people(1)))
    assert _of_type(first, "room_occupancy_change") == []
    first = rule.observe(make_frame(1.0, tracks=_people(1)))
    assert len(_of_type(first, "room_occupancy_change")) == 2

    # The person is missed for a moment: the track is retained, so no new event.
    missed = rule.observe(make_frame(2.0))
    assert _of_type(missed, "room_occupancy_change") == []


def test_occupancy_counts_distinct_tracks() -> None:
    rule = build_rule(OccupancyRule, _config(occupancy_persistence_seconds=0.0))

    assert _of_type(rule.observe(make_frame(0.0, tracks=_people(3))), "room_occupancy_change") == []
    transitions = rule.observe(make_frame(1.0, tracks=_people(3)))
    events = [t.event for t in _of_type(transitions, "room_occupancy_change")]

    assert events[0].attributes["occupancy_count"] == 3


def test_crowd_forming_opens_once_and_completes_after_release() -> None:
    rule = build_rule(
        OccupancyRule,
        _config(
            occupancy_persistence_seconds=1000.0,
            occupancy_retention_seconds=0.5,
            crowd_occupancy_threshold=3,
            crowd_persistence_seconds=2.0,
            crowd_release_seconds=2.0,
            crowd_release_hysteresis=2,
        ),
    )

    assert _of_type(rule.observe(make_frame(0.0, tracks=_people(3))), "crowd_forming") == []
    assert _of_type(rule.observe(make_frame(1.0, tracks=_people(3))), "crowd_forming") == []
    opened = _of_type(rule.observe(make_frame(2.0, tracks=_people(3))), "crowd_forming")
    assert [t.action.value for t in opened] == ["opened"]
    assert opened[0].event.attributes["occupancy_count"] == 3
    assert opened[0].event.attributes["threshold_people"] == 3

    # Still crowded: one ongoing event, never a new one per frame.
    assert _of_type(rule.observe(make_frame(3.0, tracks=_people(3))), "crowd_forming") == []

    # Within the release hysteresis band (2 > 3 - 2): remain active.
    assert _of_type(rule.observe(make_frame(4.0, tracks=_people(2))), "crowd_forming") == []

    # Drop clearly below the band and stay there for the release interval.
    assert _of_type(rule.observe(make_frame(5.0, tracks=_people(1))), "crowd_forming") == []
    assert _of_type(rule.observe(make_frame(6.0, tracks=_people(1))), "crowd_forming") == []
    resolved = _of_type(rule.observe(make_frame(7.0, tracks=_people(1))), "crowd_forming")

    assert [t.action.value for t in resolved] == ["resolved"]
    assert resolved[0].event.status.value == "completed"
    assert resolved[0].event.attributes["completion_reason"] == "occupancy_below_threshold"


def test_crowd_occupancy_updates_are_coalesced() -> None:
    rule = build_rule(
        OccupancyRule,
        _config(
            occupancy_persistence_seconds=1000.0,
            crowd_occupancy_threshold=2,
            crowd_persistence_seconds=0.0,
            crowd_release_seconds=1000.0,
            crowd_release_hysteresis=0,
        ),
    )

    opened = _of_type(rule.observe(make_frame(0.0, tracks=_people(2))), "crowd_forming")
    assert opened == []  # the first frame only starts the persistence timer
    opened = _of_type(rule.observe(make_frame(1.0, tracks=_people(2))), "crowd_forming")
    updated = _of_type(rule.observe(make_frame(2.0, tracks=_people(3))), "crowd_forming")

    assert [t.action.value for t in opened] == ["opened"]
    assert [t.action.value for t in updated] == ["updated"]
    assert updated[0].event.attributes["occupancy_count"] == 3


def test_stream_end_leaves_an_open_crowd_event_uncertain() -> None:
    rule = build_rule(
        OccupancyRule,
        _config(
            occupancy_persistence_seconds=1000.0,
            crowd_occupancy_threshold=2,
            crowd_persistence_seconds=0.0,
        ),
    )
    rule.observe(make_frame(0.0, tracks=_people(2)))
    rule.observe(make_frame(1.0, tracks=_people(2)))
    transitions = rule.on_stream_end(monotonic=2.0, observed_at=at(2.0), reason="stream_ended")

    assert [t.event.status.value for t in transitions] == ["uncertain"]
    assert transitions[0].event.attributes["completion_reason"] == "stream_ended"
