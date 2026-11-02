"""Door-open-too-long rule tests (EV-04; G §8.4)."""

from __future__ import annotations

from vision.event_engine.rules.door import DoorOpenRule
from vision.event_engine.types import DoorState, DoorStateObservation

from .event_helpers import FULL_POLYGON, at, build_rule, make_frame


def _config(**thresholds: float) -> dict:
    values = {
        "door_open_threshold_seconds": 60.0,
        "door_unknown_tolerance_seconds": 3.0,
        "door_update_interval_seconds": 30.0,
    }
    values.update(thresholds)
    return {
        "zones": [{"id": "door", "name": "Back Door", "kind": "door", "polygon": FULL_POLYGON}],
        "event_rules": {"door_zone_id": "door", "thresholds": values},
    }


def _door(state: DoorState, confidence: float = 0.8) -> DoorStateObservation:
    return DoorStateObservation(state=state, zone_id="door", confidence=confidence)


def test_without_door_state_input_the_rule_stays_inactive() -> None:
    rule = build_rule(DoorOpenRule, _config())

    transitions = []
    for second in (0.0, 30.0, 120.0):
        transitions.extend(rule.observe(make_frame(second)))

    assert transitions == []
    assert rule._event is None


def test_door_open_beyond_threshold_opens_one_event() -> None:
    rule = build_rule(DoorOpenRule, _config())

    assert rule.observe(make_frame(0.0, door_states=(_door(DoorState.OPEN),))) == []
    transitions = rule.observe(make_frame(61.0, door_states=(_door(DoorState.OPEN),)))

    assert [t.action.value for t in transitions] == ["opened"]
    event = transitions[0].event
    assert event.event_type.value == "door_open_too_long"
    assert event.status.value == "active"
    assert event.zone_name == "Back Door"
    assert event.attributes["threshold_seconds"] == 60.0
    assert event.attributes["duration_seconds"] >= 60.0
    assert event.start_time == at(0.0)
    assert event.trigger_time == at(61.0)


def test_door_is_updated_while_it_remains_open() -> None:
    rule = build_rule(DoorOpenRule, _config())
    rule.observe(make_frame(0.0, door_states=(_door(DoorState.OPEN),)))
    rule.observe(make_frame(61.0, door_states=(_door(DoorState.OPEN),)))

    updates = rule.observe(make_frame(91.0, door_states=(_door(DoorState.OPEN),)))

    assert [t.action.value for t in updates] == ["updated"]
    assert updates[0].event.attributes["duration_seconds"] >= 90.0


def test_door_closing_completes_the_event() -> None:
    rule = build_rule(DoorOpenRule, _config())
    rule.observe(make_frame(0.0, door_states=(_door(DoorState.OPEN),)))
    rule.observe(make_frame(61.0, door_states=(_door(DoorState.OPEN),)))

    transitions = rule.observe(make_frame(62.0, door_states=(_door(DoorState.CLOSED),)))

    assert [t.action.value for t in transitions] == ["resolved"]
    assert transitions[0].event.status.value == "completed"
    assert transitions[0].event.attributes["completion_reason"] == "door_closed"


def test_brief_classifier_uncertainty_does_not_duplicate_the_event() -> None:
    rule = build_rule(DoorOpenRule, _config())
    transitions = []
    transitions.extend(rule.observe(make_frame(0.0, door_states=(_door(DoorState.OPEN),))))
    transitions.extend(rule.observe(make_frame(61.0, door_states=(_door(DoorState.OPEN),))))

    unknown = _door(DoorState.UNKNOWN)
    transitions.extend(rule.observe(make_frame(62.0, door_states=(unknown,))))
    transitions.extend(rule.observe(make_frame(63.0, door_states=(unknown,))))
    transitions.extend(rule.observe(make_frame(64.0, door_states=(_door(DoorState.OPEN),))))

    actions = [t.action.value for t in transitions]
    assert actions.count("opened") == 1
    assert len([t for t in transitions if t.event.event_type.value == "door_open_too_long"]) == 1


def test_sustained_unknown_marks_the_event_uncertain_then_resumes() -> None:
    rule = build_rule(DoorOpenRule, _config())
    rule.observe(make_frame(0.0, door_states=(_door(DoorState.OPEN),)))
    rule.observe(make_frame(61.0, door_states=(_door(DoorState.OPEN),)))

    unknown = _door(DoorState.UNKNOWN)
    assert rule.observe(make_frame(62.0, door_states=(unknown,))) == []
    uncertain = rule.observe(make_frame(70.0, door_states=(unknown,)))
    assert [t.event.status.value for t in uncertain] == ["uncertain"]

    resumed = rule.observe(make_frame(80.0, door_states=(_door(DoorState.OPEN),)))
    assert [t.action.value for t in resumed] == ["updated"]
    assert resumed[0].event.status.value == "active"


def test_stream_end_leaves_an_open_door_event_incomplete() -> None:
    rule = build_rule(DoorOpenRule, _config())
    rule.observe(make_frame(0.0, door_states=(_door(DoorState.OPEN),)))
    rule.observe(make_frame(61.0, door_states=(_door(DoorState.OPEN),)))

    transitions = rule.on_stream_end(monotonic=62.0, observed_at=at(62.0), reason="stream_ended")

    assert [t.event.status.value for t in transitions] == ["uncertain"]
    assert transitions[0].event.attributes["completion_reason"] == "stream_ended"
    assert transitions[0].event.end_time == at(62.0)
