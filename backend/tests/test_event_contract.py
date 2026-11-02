"""Tests for the canonical event contract and lifecycle (Phase 5; FR-23, FR-27)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.events.lifecycle import (
    EVENT_TRANSITIONS,
    TERMINAL_EVENT_STATES,
    InvalidEventTransition,
    can_transition,
    transition,
)
from app.events.types import (
    Certainty,
    EventAction,
    EventSeverity,
    EventSnapshot,
    EventStatus,
    EventTransition,
    EventType,
    ReviewStatus,
    ensure_utc,
)

START = datetime(2026, 10, 29, 12, 0, 0, tzinfo=UTC)


def _snapshot(**overrides: object) -> EventSnapshot:
    data: dict[str, object] = {
        "event_id": "evt-1",
        "camera_id": 1,
        "event_type": EventType.PERSON_ENTERING,
        "start_time": START,
        "trigger_time": START + timedelta(seconds=1),
        "last_updated_at": START + timedelta(seconds=1),
        "status": EventStatus.ACTIVE,
        "severity": EventSeverity.INFO,
    }
    data.update(overrides)
    return EventSnapshot.model_validate(data)


# --- canonical types -----------------------------------------------------------


def test_canonical_event_types_are_exactly_the_eight_required() -> None:
    assert {member.value for member in EventType} == {
        "person_entering",
        "person_leaving",
        "room_occupancy_change",
        "crowd_forming",
        "door_open_too_long",
        "package_left_at_entrance",
        "person_motionless",
        "fall_from_bed",
    }


def test_event_status_has_the_five_lifecycle_states() -> None:
    assert {member.value for member in EventStatus} == {
        "candidate",
        "active",
        "completed",
        "uncertain",
        "cancelled",
    }


# --- timestamps ----------------------------------------------------------------


def test_ensure_utc_treats_naive_values_as_utc() -> None:
    naive = datetime(2026, 10, 29, 12, 0, 0)
    assert ensure_utc(naive) == naive.replace(tzinfo=UTC)


def test_ensure_utc_converts_offset_aware_values() -> None:
    plus_two = timezone(timedelta(hours=2))
    aware = datetime(2026, 10, 29, 14, 0, 0, tzinfo=plus_two)
    converted = ensure_utc(aware)
    assert converted.tzinfo is UTC
    assert converted == START


def test_snapshot_normalises_all_timestamps_to_utc() -> None:
    naive = datetime(2026, 10, 29, 12, 0, 0)
    snapshot = _snapshot(
        start_time=naive,
        trigger_time=naive + timedelta(seconds=1),
        last_updated_at=naive + timedelta(seconds=2),
    )
    assert snapshot.start_time == START
    assert snapshot.trigger_time.tzinfo is UTC
    assert snapshot.last_updated_at.tzinfo is UTC


def test_snapshot_defaults_are_declared() -> None:
    snapshot = _snapshot()
    assert snapshot.state_version == 1
    assert snapshot.confidence is None
    assert snapshot.certainty is Certainty.UNKNOWN
    assert snapshot.attributes == {}
    assert snapshot.evidence_refs == []
    assert snapshot.review_status is ReviewStatus.UNREVIEWED
    assert snapshot.end_time is None


# --- temporal invariants -------------------------------------------------------


def test_snapshot_rejects_trigger_before_start() -> None:
    with pytest.raises(ValidationError, match="trigger_time"):
        _snapshot(trigger_time=START - timedelta(seconds=1))


def test_snapshot_rejects_last_updated_before_start() -> None:
    with pytest.raises(ValidationError, match="last_updated_at"):
        _snapshot(last_updated_at=START - timedelta(seconds=1))


def test_snapshot_rejects_end_before_start() -> None:
    with pytest.raises(ValidationError, match="end_time"):
        _snapshot(
            status=EventStatus.COMPLETED,
            end_time=START - timedelta(seconds=1),
        )


def test_snapshot_rejects_last_updated_before_end() -> None:
    with pytest.raises(ValidationError, match="last_updated_at"):
        _snapshot(
            status=EventStatus.COMPLETED,
            end_time=START + timedelta(seconds=5),
            last_updated_at=START + timedelta(seconds=1),
        )


@pytest.mark.parametrize("status", [EventStatus.COMPLETED, EventStatus.CANCELLED])
def test_terminal_states_require_end_time(status: EventStatus) -> None:
    with pytest.raises(ValidationError, match="require end_time"):
        _snapshot(status=status)


@pytest.mark.parametrize("status", [EventStatus.CANDIDATE, EventStatus.ACTIVE])
def test_non_terminal_open_states_must_not_have_end_time(status: EventStatus) -> None:
    with pytest.raises(ValidationError, match="must not have end_time"):
        _snapshot(
            status=status,
            end_time=START + timedelta(seconds=2),
            last_updated_at=START + timedelta(seconds=2),
        )


def test_uncertain_may_carry_an_end_time() -> None:
    snapshot = _snapshot(
        status=EventStatus.UNCERTAIN,
        end_time=START + timedelta(seconds=2),
        last_updated_at=START + timedelta(seconds=2),
    )
    assert snapshot.end_time == START + timedelta(seconds=2)


# --- model constraints ---------------------------------------------------------


def test_snapshot_is_frozen() -> None:
    snapshot = _snapshot()
    with pytest.raises(ValidationError):
        snapshot.status = EventStatus.COMPLETED  # type: ignore[misc]


def test_snapshot_rejects_unknown_event_type() -> None:
    with pytest.raises(ValidationError):
        _snapshot(event_type="not_an_event")


def test_snapshot_validates_confidence_bounds() -> None:
    with pytest.raises(ValidationError):
        _snapshot(confidence=1.5)


def test_snapshot_validates_camera_id() -> None:
    with pytest.raises(ValidationError):
        _snapshot(camera_id=0)


# --- lifecycle state machine ---------------------------------------------------


def test_all_states_are_covered_by_the_transition_table() -> None:
    assert set(EVENT_TRANSITIONS) == set(EventStatus)


def test_terminal_states_have_no_legal_outgoing_transition() -> None:
    assert TERMINAL_EVENT_STATES == {EventStatus.COMPLETED, EventStatus.CANCELLED}
    for terminal in TERMINAL_EVENT_STATES:
        assert EVENT_TRANSITIONS[terminal] == frozenset()
        for target in EventStatus:
            assert not can_transition(terminal, target)


def test_expected_transitions_are_legal() -> None:
    legal = [
        (EventStatus.CANDIDATE, EventStatus.ACTIVE),
        (EventStatus.CANDIDATE, EventStatus.UNCERTAIN),
        (EventStatus.CANDIDATE, EventStatus.CANCELLED),
        (EventStatus.ACTIVE, EventStatus.COMPLETED),
        (EventStatus.ACTIVE, EventStatus.UNCERTAIN),
        (EventStatus.ACTIVE, EventStatus.CANCELLED),
        (EventStatus.UNCERTAIN, EventStatus.ACTIVE),
        (EventStatus.UNCERTAIN, EventStatus.COMPLETED),
        (EventStatus.UNCERTAIN, EventStatus.CANCELLED),
        (EventStatus.UNCERTAIN, EventStatus.UNCERTAIN),
    ]
    for current, target in legal:
        assert can_transition(current, target), (current, target)
        assert transition(current, target) is target


def test_skipping_directly_to_completed_from_candidate_is_illegal() -> None:
    assert not can_transition(EventStatus.CANDIDATE, EventStatus.COMPLETED)
    with pytest.raises(InvalidEventTransition):
        transition(EventStatus.CANDIDATE, EventStatus.COMPLETED)


def test_completed_cannot_reopen() -> None:
    for target in EventStatus:
        with pytest.raises(InvalidEventTransition):
            transition(EventStatus.COMPLETED, target)


# --- transition records --------------------------------------------------------


def test_transition_accepts_consistent_action_and_status() -> None:
    active = EventTransition(action=EventAction.OPENED, event=_snapshot())
    assert active.event.status is EventStatus.ACTIVE

    resolved = EventTransition(
        action=EventAction.RESOLVED,
        event=_snapshot(
            status=EventStatus.COMPLETED,
            end_time=START + timedelta(seconds=3),
            last_updated_at=START + timedelta(seconds=3),
        ),
    )
    assert resolved.event.status is EventStatus.COMPLETED


def test_transition_rejects_resolved_with_non_completed_status() -> None:
    with pytest.raises(ValidationError, match="resolved"):
        EventTransition(action=EventAction.RESOLVED, event=_snapshot())


def test_transition_rejects_cancelled_with_non_cancelled_status() -> None:
    with pytest.raises(ValidationError, match="cancelled"):
        EventTransition(action=EventAction.CANCELLED, event=_snapshot())


def test_transition_rejects_marked_uncertain_without_uncertain_status() -> None:
    with pytest.raises(ValidationError, match="marked_uncertain"):
        EventTransition(action=EventAction.MARKED_UNCERTAIN, event=_snapshot())


def test_transition_rejects_opened_or_updated_terminal_status() -> None:
    completed = _snapshot(
        status=EventStatus.COMPLETED,
        end_time=START + timedelta(seconds=3),
        last_updated_at=START + timedelta(seconds=3),
    )
    with pytest.raises(ValidationError, match="opened"):
        EventTransition(action=EventAction.OPENED, event=completed)
    with pytest.raises(ValidationError, match="updated"):
        EventTransition(action=EventAction.UPDATED, event=completed)
