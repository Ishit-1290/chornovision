"""Entry/exit rule tests (EV-01, EV-02; G §8.1/§8.2)."""

from __future__ import annotations

from vision.event_engine.rules.boundary import BoundaryCrossingRule

from .event_helpers import FULL_POLYGON, build_rule, make_frame, person

OUTSIDE = (45.0, 20.0, 55.0, 40.0)  # bottom-centre y = 0.40 (above the line)
INSIDE = (45.0, 40.0, 55.0, 60.0)  # bottom-centre y = 0.60 (below the line)


def _config(*, confirm_frames: int = 2, cooldown: float = 2.0) -> dict:
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
            }
        ],
        "event_rules": {
            "entrance_zone_id": "entrance",
            "thresholds": {
                "boundary_confirm_frames": confirm_frames,
                "boundary_cooldown_seconds": cooldown,
            },
        },
    }


def test_person_already_inside_when_stream_starts_is_not_entering() -> None:
    rule = build_rule(BoundaryCrossingRule, _config())

    transitions = []
    for second in range(3):
        transitions.extend(rule.observe(make_frame(float(second), tracks=(person(bbox=INSIDE),))))

    assert transitions == []


def test_person_disappearing_without_a_crossing_is_not_leaving() -> None:
    rule = build_rule(BoundaryCrossingRule, _config())

    rule.observe(make_frame(0.0, tracks=(person(bbox=INSIDE),)))
    rule.observe(make_frame(1.0, tracks=(person(bbox=INSIDE),)))
    transitions = rule.observe(make_frame(2.0))

    assert transitions == []


def test_inward_crossing_emits_one_instantaneous_entering_event() -> None:
    rule = build_rule(BoundaryCrossingRule, _config())

    assert rule.observe(make_frame(0.0, tracks=(person(bbox=OUTSIDE),))) == []
    assert rule.observe(make_frame(1.0, tracks=(person(bbox=INSIDE),))) == []
    transitions = rule.observe(make_frame(2.0, tracks=(person(bbox=INSIDE),)))

    assert [transition.action.value for transition in transitions] == [
        "opened",
        "resolved",
    ]
    opened, resolved = (transition.event for transition in transitions)
    assert opened.event_type.value == "person_entering"
    assert opened.status.value == "active"
    assert resolved.status.value == "completed"
    assert opened.event_id == resolved.event_id
    assert resolved.state_version == opened.state_version + 1
    assert opened.entity_id == 1
    assert opened.zone_id == "entrance"
    assert opened.zone_name == "Main Entrance"
    assert opened.attributes["direction"] == "inward"
    assert opened.start_time <= opened.trigger_time
    assert resolved.end_time == opened.trigger_time


def test_outward_crossing_emits_leaving() -> None:
    rule = build_rule(BoundaryCrossingRule, _config())

    rule.observe(make_frame(0.0, tracks=(person(bbox=INSIDE),)))
    rule.observe(make_frame(1.0, tracks=(person(bbox=INSIDE),)))
    assert rule.observe(make_frame(2.0, tracks=(person(bbox=OUTSIDE),))) == []
    transitions = rule.observe(make_frame(3.0, tracks=(person(bbox=OUTSIDE),)))

    events = [transition.event for transition in transitions]
    assert [event.event_type.value for event in events] == [
        "person_leaving",
        "person_leaving",
    ]
    assert events[0].attributes["direction"] == "outward"
    assert events[-1].status.value == "completed"


def test_crossing_needs_the_configured_confirmation_frames() -> None:
    rule = build_rule(BoundaryCrossingRule, _config(confirm_frames=3))

    rule.observe(make_frame(0.0, tracks=(person(bbox=OUTSIDE),)))
    assert rule.observe(make_frame(1.0, tracks=(person(bbox=INSIDE),))) == []
    assert rule.observe(make_frame(2.0, tracks=(person(bbox=INSIDE),))) == []
    transitions = rule.observe(make_frame(3.0, tracks=(person(bbox=INSIDE),)))

    assert [transition.event.event_type.value for transition in transitions] == [
        "person_entering",
        "person_entering",
    ]


def test_cooldown_suppresses_a_rapid_immediate_re_cross() -> None:
    rule = build_rule(BoundaryCrossingRule, _config(confirm_frames=1, cooldown=5.0))

    rule.observe(make_frame(0.0, tracks=(person(bbox=OUTSIDE),)))
    first = rule.observe(make_frame(1.0, tracks=(person(bbox=INSIDE),)))
    assert [t.event.event_type.value for t in first] == [
        "person_entering",
        "person_entering",
    ]

    # Crossing back immediately is suppressed by the cooldown.
    assert rule.observe(make_frame(2.0, tracks=(person(bbox=OUTSIDE),))) == []


def test_each_valid_crossing_is_a_separate_event_occurrence() -> None:
    rule = build_rule(BoundaryCrossingRule, _config(confirm_frames=1, cooldown=0.0))

    rule.observe(make_frame(0.0, tracks=(person(bbox=OUTSIDE),)))
    entering = rule.observe(make_frame(1.0, tracks=(person(bbox=INSIDE),)))
    leaving = rule.observe(make_frame(2.0, tracks=(person(bbox=OUTSIDE),)))

    assert entering[0].event.event_id != leaving[0].event.event_id
    assert entering[0].event.event_type.value == "person_entering"
    assert leaving[0].event.event_type.value == "person_leaving"


def test_identical_ordered_input_produces_identical_event_ids() -> None:
    frames = [
        make_frame(0.0, tracks=(person(bbox=OUTSIDE),)),
        make_frame(1.0, tracks=(person(bbox=INSIDE),)),
        make_frame(2.0, tracks=(person(bbox=INSIDE),)),
    ]
    first_rule = build_rule(BoundaryCrossingRule, _config())
    second_rule = build_rule(BoundaryCrossingRule, _config())

    first = [t for frame in frames for t in first_rule.observe(frame)]
    second = [t for frame in frames for t in second_rule.observe(frame)]

    assert [t.event.event_id for t in first] == [t.event.event_id for t in second]


def test_track_state_is_bounded() -> None:
    configuration = _config()
    configuration["event_rules"]["thresholds"]["max_tracked_entities"] = 3
    rule = build_rule(BoundaryCrossingRule, configuration)

    tracks = tuple(person(track_id=track_id) for track_id in range(1, 11))
    rule.observe(make_frame(0.0, tracks=tracks))

    assert len(rule._state) <= 3  # bounded-state assertion
