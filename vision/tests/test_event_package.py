"""Package-left-at-entrance rule tests (EV-05; G §8.5)."""

from __future__ import annotations

from vision.event_engine.rules.package import PackageRule

from .event_helpers import FULL_POLYGON, at, build_rule, make_frame, person

PACKAGE = (46.0, 46.0, 54.0, 54.0)
PACKAGE_MOVED = (56.0, 46.0, 64.0, 54.0)
PERSON_NEAR = (46.0, 40.0, 54.0, 50.0)
PERSON_FAR = (5.0, 5.0, 15.0, 15.0)


def _config(**thresholds: float) -> dict:
    values = {
        "package_stationary_seconds": 30.0,
        "package_stationary_tolerance": 0.02,
        "package_absence_tolerance_seconds": 5.0,
        "package_person_proximity": 0.15,
        "package_update_interval_seconds": 30.0,
    }
    values.update(thresholds)
    return {
        "zones": [
            {
                "id": "porch",
                "name": "Porch",
                "kind": "package_area",
                "polygon": FULL_POLYGON,
            }
        ],
        "event_rules": {
            "package_zone_id": "porch",
            "package_classes": ["package", "parcel", "box"],
            "thresholds": values,
        },
    }


def _package(track_id: int = 5, bbox=PACKAGE, confidence: float = 0.7):
    return person(track_id=track_id, bbox=bbox, class_name="package", confidence=confidence)


def test_without_package_detections_the_rule_stays_inactive() -> None:
    rule = build_rule(PackageRule, _config())

    transitions = []
    for second in (0.0, 30.0, 60.0):
        transitions.extend(rule.observe(make_frame(second, tracks=(person(),))))

    assert transitions == []


def test_stationary_package_beyond_threshold_opens_one_event() -> None:
    rule = build_rule(PackageRule, _config())

    assert rule.observe(make_frame(0.0, tracks=(_package(),))) == []
    assert rule.observe(make_frame(29.0, tracks=(_package(),))) == []
    transitions = rule.observe(make_frame(30.0, tracks=(_package(),)))

    assert [t.action.value for t in transitions] == ["opened"]
    event = transitions[0].event
    assert event.event_type.value == "package_left_at_entrance"
    assert event.status.value == "active"
    assert event.entity_id == 5
    assert event.zone_name == "Porch"
    assert event.attributes["duration_seconds"] >= 30.0
    assert event.start_time == at(0.0)


def test_moving_package_restarts_the_stationary_timer() -> None:
    rule = build_rule(PackageRule, _config())

    rule.observe(make_frame(0.0, tracks=(_package(),)))
    rule.observe(make_frame(29.0, tracks=(_package(),)))
    # Move just before the threshold: the timer restarts.
    assert rule.observe(make_frame(29.5, tracks=(_package(bbox=PACKAGE_MOVED),))) == []
    assert rule.observe(make_frame(40.0, tracks=(_package(bbox=PACKAGE_MOVED),))) == []
    transitions = rule.observe(make_frame(60.0, tracks=(_package(bbox=PACKAGE_MOVED),)))

    assert [t.event.event_type.value for t in transitions] == ["package_left_at_entrance"]


def test_package_outside_the_configured_zone_is_ignored() -> None:
    configuration = _config()
    configuration["zones"][0]["polygon"] = [
        {"x": 0.0, "y": 0.0},
        {"x": 1.0, "y": 0.0},
        {"x": 1.0, "y": 0.5},
        {"x": 0.0, "y": 0.5},
    ]
    rule = build_rule(PackageRule, configuration)

    transitions = []
    for second in (0.0, 30.0, 60.0):
        transitions.extend(
            rule.observe(make_frame(second, tracks=(_package(bbox=(46.0, 80.0, 54.0, 90.0)),)))
        )

    assert transitions == []


def test_package_removal_completes_the_event() -> None:
    rule = build_rule(PackageRule, _config())
    rule.observe(make_frame(0.0, tracks=(_package(),)))
    rule.observe(make_frame(30.0, tracks=(_package(),)))

    assert rule.observe(make_frame(33.0)) == []
    transitions = rule.observe(make_frame(36.0))

    assert [t.action.value for t in transitions] == ["resolved"]
    assert transitions[0].event.attributes["completion_reason"] == "package_removed"


def test_person_nearby_marks_the_package_as_possible_unattended() -> None:
    rule = build_rule(PackageRule, _config())
    person_near = person(track_id=1, bbox=PERSON_NEAR)

    rule.observe(make_frame(0.0, tracks=(_package(), person_near)))
    transitions = rule.observe(make_frame(30.0, tracks=(_package(), person_near)))

    event = transitions[0].event
    assert event.attributes["person_nearby"] is True
    assert event.certainty.value == "low"


def test_person_far_away_does_not_force_low_certainty() -> None:
    rule = build_rule(PackageRule, _config())
    person_far = person(track_id=1, bbox=PERSON_FAR)

    rule.observe(make_frame(0.0, tracks=(_package(), person_far)))
    transitions = rule.observe(make_frame(30.0, tracks=(_package(), person_far)))

    event = transitions[0].event
    assert event.attributes["person_nearby"] is False
    assert event.certainty.value == "high"


def test_stream_end_leaves_an_open_package_event_incomplete() -> None:
    rule = build_rule(PackageRule, _config())
    rule.observe(make_frame(0.0, tracks=(_package(),)))
    rule.observe(make_frame(30.0, tracks=(_package(),)))

    transitions = rule.on_stream_end(monotonic=31.0, observed_at=at(31.0), reason="stream_ended")

    assert [t.event.status.value for t in transitions] == ["uncertain"]
    assert transitions[0].event.attributes["completion_reason"] == "stream_ended"
