"""Tests for the per-camera lifecycle state machine (FR-03, FR-05)."""

from __future__ import annotations

import pytest

from app.models.camera import CameraStatus
from app.services.lifecycle import (
    LEGAL_TRANSITIONS,
    PROCESSING_STATES,
    STARTABLE_STATES,
    InvalidStateTransition,
    can_transition,
    coerce_status,
    transition,
)


def test_every_state_has_a_transition_entry() -> None:
    assert set(LEGAL_TRANSITIONS) == set(CameraStatus)


def test_configured_can_start_stop_or_fail() -> None:
    assert can_transition(CameraStatus.CONFIGURED, CameraStatus.CONNECTING)
    assert can_transition(CameraStatus.CONFIGURED, CameraStatus.STOPPED)
    assert can_transition(CameraStatus.CONFIGURED, CameraStatus.FAILED)


def test_connecting_reaches_active_or_disconnected() -> None:
    assert can_transition(CameraStatus.CONNECTING, CameraStatus.ACTIVE)
    assert can_transition(CameraStatus.CONNECTING, CameraStatus.DISCONNECTED)


def test_active_can_degrade_disconnect_or_reconnect() -> None:
    assert can_transition(CameraStatus.ACTIVE, CameraStatus.DEGRADED)
    assert can_transition(CameraStatus.ACTIVE, CameraStatus.DISCONNECTED)
    assert can_transition(CameraStatus.ACTIVE, CameraStatus.RECONNECTING)


def test_stopped_can_restart() -> None:
    assert can_transition(CameraStatus.STOPPED, CameraStatus.CONNECTING)
    assert can_transition(CameraStatus.STOPPED, CameraStatus.CONFIGURED)


def test_failed_can_recover_or_stop() -> None:
    assert can_transition(CameraStatus.FAILED, CameraStatus.CONNECTING)
    assert can_transition(CameraStatus.FAILED, CameraStatus.STOPPED)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (CameraStatus.CONFIGURED, CameraStatus.ACTIVE),  # must connect first
        (CameraStatus.DISCONNECTED, CameraStatus.ACTIVE),  # must reconnect first
        (CameraStatus.DISCONNECTED, CameraStatus.DEGRADED),
        (CameraStatus.STOPPED, CameraStatus.ACTIVE),
        (CameraStatus.ACTIVE, CameraStatus.CONNECTING),
        (CameraStatus.CONFIGURED, CameraStatus.DISCONNECTED),
    ],
)
def test_illegal_transitions_are_rejected(current: CameraStatus, target: CameraStatus) -> None:
    assert not can_transition(current, target)
    with pytest.raises(InvalidStateTransition):
        transition(current, target)


def test_disconnected_is_distinct_from_active() -> None:
    # FR-05: a disconnected stream is not "a stream with no activity".
    assert CameraStatus.DISCONNECTED != CameraStatus.ACTIVE
    # A disconnected camera cannot jump straight back to active without recovery.
    assert not can_transition(CameraStatus.DISCONNECTED, CameraStatus.ACTIVE)
    # Recovery must pass through the reconnect path.
    assert can_transition(CameraStatus.DISCONNECTED, CameraStatus.RECONNECTING)
    assert can_transition(CameraStatus.RECONNECTING, CameraStatus.ACTIVE)


def test_transition_returns_target_status() -> None:
    assert transition("configured", "connecting") is CameraStatus.CONNECTING


def test_transition_accepts_strings_and_enums() -> None:
    assert can_transition("connecting", CameraStatus.ACTIVE)
    assert can_transition(CameraStatus.CONNECTING, "active")


def test_processing_and_startable_state_sets() -> None:
    assert CameraStatus.ACTIVE in PROCESSING_STATES
    assert CameraStatus.DISCONNECTED in PROCESSING_STATES
    assert CameraStatus.CONFIGURED not in PROCESSING_STATES
    assert CameraStatus.STOPPED not in PROCESSING_STATES
    assert STARTABLE_STATES == {CameraStatus.CONFIGURED, CameraStatus.STOPPED}


def test_coerce_status_rejects_unknown_value() -> None:
    with pytest.raises(ValueError):
        coerce_status("sleeping")
