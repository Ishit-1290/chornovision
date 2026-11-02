"""Potential-fall-from-bed rule tests (EV-07; G §8.7)."""

from __future__ import annotations

from vision.event_engine.rules.fall import FallRule
from vision.event_engine.types import PoseObservation, Posture

from .event_helpers import at, build_rule, make_frame, person

ON_BED = (40.0, 10.0, 60.0, 40.0)
ON_FLOOR = (40.0, 60.0, 60.0, 90.0)


def _config(**thresholds: float) -> dict:
    values = {
        "fall_transition_window_seconds": 5.0,
        "fall_ambiguous_window_seconds": 15.0,
        "fall_min_bed_seconds": 0.0,
        "fall_low_height_ratio": 0.18,
        "fall_confirmation_seconds": 5.0,
        "fall_update_interval_seconds": 5.0,
    }
    values.update(thresholds)
    return {
        "zones": [
            {
                "id": "bed",
                "name": "Bed",
                "kind": "bed",
                "polygon": [
                    {"x": 0.0, "y": 0.0},
                    {"x": 1.0, "y": 0.0},
                    {"x": 1.0, "y": 0.5},
                    {"x": 0.0, "y": 0.5},
                ],
            },
            {
                "id": "floor",
                "name": "Floor",
                "kind": "floor",
                "polygon": [
                    {"x": 0.0, "y": 0.5},
                    {"x": 1.0, "y": 0.5},
                    {"x": 1.0, "y": 1.0},
                    {"x": 0.0, "y": 1.0},
                ],
            },
        ],
        "event_rules": {
            "bed_zone_id": "bed",
            "floor_zone_id": "floor",
            "thresholds": values,
        },
    }


def _pose(posture: Posture, *, height_ratio: float | None = 0.3, confidence: float = 0.8):
    return PoseObservation(
        track_id=1, posture=posture, height_ratio=height_ratio, confidence=confidence
    )


def test_without_pose_input_the_rule_stays_inactive() -> None:
    rule = build_rule(FallRule, _config())

    transitions = []
    transitions.extend(rule.observe(make_frame(0.0, tracks=(person(bbox=ON_BED),))))
    transitions.extend(rule.observe(make_frame(1.0, tracks=(person(bbox=ON_FLOOR),))))

    assert transitions == []


def test_lying_in_bed_does_not_trigger() -> None:
    rule = build_rule(FallRule, _config())

    transitions = []
    for second in (0.0, 1.0, 2.0):
        transitions.extend(
            rule.observe(
                make_frame(
                    second,
                    tracks=(person(bbox=ON_BED),),
                    poses=(_pose(Posture.LYING),),
                )
            )
        )

    assert transitions == []


def test_observed_bed_to_floor_transition_opens_an_active_possible_fall() -> None:
    rule = build_rule(FallRule, _config())

    rule.observe(make_frame(0.0, tracks=(person(bbox=ON_BED),), poses=(_pose(Posture.LYING),)))
    transitions = rule.observe(
        make_frame(1.0, tracks=(person(bbox=ON_FLOOR),), poses=(_pose(Posture.LYING),))
    )

    assert [t.action.value for t in transitions] == ["opened"]
    event = transitions[0].event
    assert event.event_type.value == "fall_from_bed"
    assert event.status.value == "active"
    assert event.severity.value == "critical"
    assert event.attributes["observed_bed_transition"] is True
    assert event.attributes["in_floor_zone"] is True
    assert event.attributes["bed_zone_name"] == "Bed"
    assert event.start_time == at(0.0)


def test_floor_posture_without_an_observed_transition_is_uncertain() -> None:
    rule = build_rule(FallRule, _config())

    transitions = rule.observe(
        make_frame(0.0, tracks=(person(bbox=ON_FLOOR),), poses=(_pose(Posture.LYING),))
    )

    assert [t.action.value for t in transitions] == ["opened"]
    assert transitions[0].event.status.value == "uncertain"
    assert transitions[0].event.attributes["observed_bed_transition"] is False
    assert transitions[0].event.certainty.value == "unknown"


def test_sustained_upright_posture_completes_the_event() -> None:
    rule = build_rule(FallRule, _config())
    rule.observe(make_frame(0.0, tracks=(person(bbox=ON_BED),), poses=(_pose(Posture.LYING),)))
    rule.observe(make_frame(1.0, tracks=(person(bbox=ON_FLOOR),), poses=(_pose(Posture.LYING),)))

    assert (
        rule.observe(
            make_frame(2.0, tracks=(person(bbox=ON_FLOOR),), poses=(_pose(Posture.UPRIGHT),))
        )
        == []
    )
    transitions = rule.observe(
        make_frame(8.0, tracks=(person(bbox=ON_FLOOR),), poses=(_pose(Posture.UPRIGHT),))
    )

    assert [t.action.value for t in transitions] == ["resolved"]
    assert transitions[0].event.attributes["completion_reason"] == "person_upright"


def test_stream_end_leaves_an_open_fall_event_incomplete() -> None:
    rule = build_rule(FallRule, _config())
    rule.observe(make_frame(0.0, tracks=(person(bbox=ON_BED),), poses=(_pose(Posture.LYING),)))
    rule.observe(make_frame(1.0, tracks=(person(bbox=ON_FLOOR),), poses=(_pose(Posture.LYING),)))

    transitions = rule.on_stream_end(monotonic=2.0, observed_at=at(2.0), reason="stream_ended")

    assert [t.event.status.value for t in transitions] == ["uncertain"]
    assert transitions[0].event.attributes["completion_reason"] == "stream_ended"
