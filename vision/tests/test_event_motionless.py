"""Person-motionless rule tests (EV-06; G §8.6)."""

from __future__ import annotations

from vision.event_engine.rules.motionless import MotionlessRule

from .event_helpers import at, build_rule, make_frame, person

STILL = (45.0, 20.0, 55.0, 40.0)
MOVED = (45.0, 20.0, 55.0, 90.0)


def _config(**thresholds: float) -> dict:
    values = {
        "motionless_duration_seconds": 120.0,
        "motionless_movement_threshold": 0.01,
        "motionless_absence_tolerance_seconds": 3.0,
        "motionless_update_interval_seconds": 30.0,
        "motionless_min_observations": 5,
    }
    values.update(thresholds)
    return {"event_rules": {"thresholds": values}}


def _frames_until_open(rule: MotionlessRule):
    transitions = []
    for second in (0.0, 30.0, 60.0, 90.0, 120.0):
        transitions.extend(rule.observe(make_frame(second, tracks=(person(bbox=STILL),))))
    return transitions


def test_short_inactivity_does_not_open_an_event() -> None:
    rule = build_rule(MotionlessRule, _config())

    transitions = []
    for second in (0.0, 30.0, 60.0):
        transitions.extend(rule.observe(make_frame(second, tracks=(person(bbox=STILL),))))

    assert transitions == []


def test_sustained_stillness_opens_one_event() -> None:
    rule = build_rule(MotionlessRule, _config())

    transitions = _frames_until_open(rule)

    assert [t.action.value for t in transitions] == ["opened"]
    event = transitions[0].event
    assert event.event_type.value == "person_motionless"
    assert event.status.value == "active"
    assert event.entity_id == 1
    assert event.attributes["duration_seconds"] >= 120.0


def test_event_updates_while_the_person_remains_still() -> None:
    rule = build_rule(MotionlessRule, _config())
    _frames_until_open(rule)

    transitions = rule.observe(make_frame(150.0, tracks=(person(bbox=STILL),)))

    assert [t.action.value for t in transitions] == ["updated"]
    assert transitions[0].event.attributes["duration_seconds"] >= 150.0


def test_meaningful_movement_completes_the_event() -> None:
    rule = build_rule(MotionlessRule, _config())
    _frames_until_open(rule)

    transitions = rule.observe(make_frame(150.0, tracks=(person(bbox=MOVED),)))

    assert [t.action.value for t in transitions] == ["resolved"]
    assert transitions[0].event.status.value == "completed"
    assert transitions[0].event.attributes["completion_reason"] == "movement_resumed"


def test_losing_the_track_marks_the_event_uncertain() -> None:
    rule = build_rule(MotionlessRule, _config())
    _frames_until_open(rule)

    transitions = rule.observe(make_frame(124.0))

    assert [t.event.status.value for t in transitions] == ["uncertain"]
    assert transitions[0].event.attributes["completion_reason"] == "track_not_observed"
    assert transitions[0].event.end_time == at(124.0)


def test_after_movement_a_new_still_period_is_a_new_event() -> None:
    rule = build_rule(MotionlessRule, _config())
    first = _frames_until_open(rule)
    rule.observe(make_frame(150.0, tracks=(person(bbox=MOVED),)))

    transitions = []
    for second in (150.0, 180.0, 210.0, 240.0, 270.0, 300.0):
        transitions.extend(rule.observe(make_frame(second, tracks=(person(bbox=MOVED),))))

    opened = [t for t in transitions if t.action.value == "opened"]
    assert len(opened) == 1
    assert opened[0].event.event_id != first[0].event.event_id
