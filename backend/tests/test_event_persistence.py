"""Event persistence invariants (idempotency, staleness, lifecycle; Phase 6)."""

from __future__ import annotations

import pytest

from app.events.types import EventAction, EventStatus, EventType
from app.models.event import Event
from app.repositories import events as events_repo
from app.services import camera_service, event_service

from . import event_builders as eb

CAMERA_ID = 1


@pytest.fixture
def camera(db_session_factory, admin_env):
    db = db_session_factory()
    try:
        return camera_service.create_camera(
            db, name="front-door", stream_reference="rtsp://192.168.1.10:554/s1"
        )
    finally:
        db.close()


def _count_transitions(db, event: Event) -> int:
    return len(events_repo.list_transitions(db, event.id))


def test_opening_transition_creates_event_and_history(db_session_factory, camera) -> None:
    db = db_session_factory()
    try:
        result = event_service.record_transition(db, eb.opened(camera_id=camera.id))
        assert result.applied is True
        event = result.event
        assert event.event_id == eb.snapshot().event_id
        assert event.camera_id == camera.id
        assert event.event_type == EventType.PERSON_ENTERING.value
        assert event.status == EventStatus.ACTIVE.value
        assert event.state_version == 1
        assert event.message  # deterministic template rendered
        assert event.rule_version == "phase5-v1"
        assert event.config_version == "v1"
        assert _count_transitions(db, event) == 1
    finally:
        db.close()


def test_repeated_delivery_is_idempotent(db_session_factory, camera) -> None:
    db = db_session_factory()
    try:
        first = event_service.record_transition(db, eb.opened(camera_id=camera.id))
        second = event_service.record_transition(db, eb.opened(camera_id=camera.id))
        assert first.applied is True
        assert second.applied is False
        assert second.event.id == first.event.id
        assert _count_transitions(db, first.event) == 1
    finally:
        db.close()


def test_stale_update_is_rejected(db_session_factory, camera) -> None:
    db = db_session_factory()
    try:
        event_service.record_transition(db, eb.opened(camera_id=camera.id, state_version=1))
        newer = event_service.record_transition(
            db, eb.updated(camera_id=camera.id, state_version=3, confidence=0.5)
        )
        assert newer.applied is True
        # An older revision arriving late must not overwrite the newer state.
        stale = event_service.record_transition(
            db, eb.updated(camera_id=camera.id, state_version=2, confidence=0.99)
        )
        assert stale.applied is False
        assert stale.event.state_version == 3
        assert stale.event.confidence == 0.5
    finally:
        db.close()


def test_lifecycle_transitions_are_appended_in_order(db_session_factory, camera) -> None:
    db = db_session_factory()
    try:
        event_service.record_transition(db, eb.opened(camera_id=camera.id, state_version=1))
        event_service.record_transition(
            db, eb.updated(camera_id=camera.id, state_version=2, confidence=0.7)
        )
        result = event_service.record_transition(
            db, eb.resolved(camera_id=camera.id, state_version=3)
        )
        history = events_repo.list_transitions(db, result.event.id)
        assert [row.state_version for row in history] == [1, 2, 3]
        assert [row.action for row in history] == [
            EventAction.OPENED.value,
            EventAction.UPDATED.value,
            EventAction.RESOLVED.value,
        ]
        assert history[-1].status == EventStatus.COMPLETED.value
        assert result.event.end_time is not None
    finally:
        db.close()


def test_terminal_event_is_immutable(db_session_factory, camera) -> None:
    db = db_session_factory()
    try:
        event_service.record_transition(db, eb.opened(camera_id=camera.id, state_version=1))
        done = event_service.record_transition(
            db, eb.resolved(camera_id=camera.id, state_version=2)
        )
        assert done.event.status == EventStatus.COMPLETED.value
        # A later, higher-version update must never mutate a terminal event.
        later = event_service.record_transition(
            db, eb.updated(camera_id=camera.id, state_version=5)
        )
        assert later.applied is False
        assert later.event.status == EventStatus.COMPLETED.value
        assert later.event.state_version == 2
    finally:
        db.close()


def test_unknown_camera_is_rejected(db_session_factory, camera) -> None:
    db = db_session_factory()
    try:
        with pytest.raises(event_service.UnknownCamera):
            event_service.record_transition(db, eb.opened(camera_id=999))
    finally:
        db.close()


def test_message_is_rendered_from_camera_name(db_session_factory, camera) -> None:
    db = db_session_factory()
    try:
        result = event_service.record_transition(db, eb.opened(camera_id=camera.id))
        assert "front-door" in result.event.message
    finally:
        db.close()


def test_attributes_are_persisted_as_json(db_session_factory, camera) -> None:
    db = db_session_factory()
    try:
        result = event_service.record_transition(
            db,
            eb.opened(
                camera_id=camera.id,
                attributes={
                    "rule_version": "phase5-v1",
                    "config_version": "v2",
                    "occupancy_count": 3,
                },
            ),
        )
        assert result.event.attributes["occupancy_count"] == 3
        assert result.event.config_version == "v2"
    finally:
        db.close()
