"""Tests for the deterministic event message templates and renderer (FR-30–FR-34)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.event_messages.renderer import (
    MAX_TEXT_LENGTH,
    EventMessageContext,
    MessageRenderError,
    format_event_time,
    message_context_from_event,
    render_event,
    render_event_message,
    sanitize_display_text,
)
from app.event_messages.templates import ALLOWED_FIELDS, FALLBACKS, TEMPLATES
from app.events.types import EventSeverity, EventSnapshot, EventStatus, EventType

START = datetime(2026, 10, 29, 12, 0, 0, tzinfo=UTC)


def _context(**overrides: object) -> EventMessageContext:
    data: dict[str, object] = {
        "camera_name": "Camera 1",
        "zone_name": "Front door",
        "occupancy_count": 4,
        "duration_seconds": 61.6,
        "threshold_seconds": 60,
        "event_time": START,
        "bed_zone_name": "Bed A",
    }
    data.update(overrides)
    return EventMessageContext.model_validate(data)


# --- template inventory --------------------------------------------------------


def test_every_canonical_event_type_has_a_template() -> None:
    assert set(TEMPLATES) == set(EventType)


def test_every_template_field_is_allowed_and_declared() -> None:
    from string import Formatter

    formatter = Formatter()
    for event_type, message_template in TEMPLATES.items():
        placeholders = {
            field_name
            for _literal, field_name, _spec, _conversion in formatter.parse(
                message_template.template
            )
            if field_name is not None
        }
        assert placeholders == set(message_template.fields), event_type
        assert placeholders <= ALLOWED_FIELDS, event_type


def test_every_fallback_field_is_a_project_concept() -> None:
    assert set(FALLBACKS) == ALLOWED_FIELDS
    for fallback in FALLBACKS.values():
        assert fallback


@pytest.mark.parametrize("event_type", list(EventType))
def test_each_template_renders_a_complete_single_line_message(
    event_type: EventType,
) -> None:
    message = render_event_message(event_type, _context())
    assert message
    assert "\n" not in message
    assert "{" not in message and "}" not in message
    assert message.endswith(".")


# --- fixed wording -------------------------------------------------------------


def test_person_entering_wording_is_fixed() -> None:
    assert render_event_message(EventType.PERSON_ENTERING, _context()) == (
        "Person detected entering Front door on camera Camera 1 at 2026-10-29 12:00:00 UTC."
    )


def test_person_leaving_wording_is_fixed() -> None:
    assert render_event_message(EventType.PERSON_LEAVING, _context()) == (
        "Person detected leaving Front door on camera Camera 1 at 2026-10-29 12:00:00 UTC."
    )


def test_room_occupancy_change_wording_is_distinct_from_crowd() -> None:
    occupancy = render_event_message(EventType.ROOM_OCCUPANCY_CHANGE, _context())
    crowd = render_event_message(EventType.CROWD_FORMING, _context())
    assert occupancy.startswith("Occupancy update in Front door")
    assert crowd.startswith("Occupancy threshold reached in Front door")
    assert occupancy != crowd
    assert "Detected occupancy: 4 people" in occupancy


def test_door_wording_includes_rounded_duration_and_threshold() -> None:
    assert render_event_message(EventType.DOOR_OPEN_TOO_LONG, _context()) == (
        "Door at Front door has remained open for 62 seconds on camera Camera 1. "
        "Threshold: 60 seconds."
    )


def test_package_wording_is_hedged_and_deterministic() -> None:
    assert render_event_message(EventType.PACKAGE_LEFT_AT_ENTRANCE, _context()) == (
        "A package appears to have been left unattended in Front door on camera "
        "Camera 1 for 62 seconds."
    )


def test_motionless_wording_asks_for_review() -> None:
    message = render_event_message(EventType.PERSON_MOTIONLESS, _context())
    assert "limited detectable movement" in message
    assert "Review the evidence" in message


def test_fall_wording_is_hedged_and_names_the_bed_area() -> None:
    message = render_event_message(EventType.FALL_FROM_BED, _context())
    assert message.startswith("Potential fall detected near Bed A on camera Camera 1")
    assert "Review the evidence to assess the event." in message


def test_rendering_is_deterministic() -> None:
    first = render_event_message(EventType.CROWD_FORMING, _context())
    second = render_event_message(EventType.CROWD_FORMING, _context())
    assert first == second


# --- fallbacks -----------------------------------------------------------------


@pytest.mark.parametrize("event_type", list(EventType))
def test_empty_context_uses_fallbacks_instead_of_failing(event_type: EventType) -> None:
    message = render_event_message(event_type)
    assert "Unknown" in message or "unknown number" in message or "unknown time" in message


def test_fallbacks_have_the_documented_values() -> None:
    message = render_event_message(EventType.PERSON_ENTERING)
    assert "entering Unknown zone on camera Unknown at an unknown time" in message


def test_missing_bed_name_falls_back_to_the_zone_then_generic_default() -> None:
    with_zone = render_event_message(
        EventType.FALL_FROM_BED, EventMessageContext(zone_name="Room 2")
    )
    assert "near Room 2" in with_zone
    without_zone = render_event_message(EventType.FALL_FROM_BED, EventMessageContext())
    assert "near the bed area" in without_zone


def test_duration_and_threshold_are_rendered_as_whole_seconds() -> None:
    message = render_event_message(
        EventType.DOOR_OPEN_TOO_LONG,
        EventMessageContext(duration_seconds=60.4, threshold_seconds=59.6),
    )
    assert "for 60 seconds" in message
    assert "Threshold: 60 seconds" in message


# --- sanitisation --------------------------------------------------------------


def test_control_characters_and_markup_are_removed() -> None:
    assert sanitize_display_text("Front\x00door\n<script>", fallback="x") == ("Front door script")


def test_stream_url_and_credentials_are_redacted() -> None:
    text = sanitize_display_text("rtsp://admin:secret@10.0.0.1/live", fallback="x")
    assert text == "[redacted-url]"
    assert "secret" not in text
    assert "10.0.0.1" not in text

    bare = sanitize_display_text("admin:secret@camera", fallback="x")
    assert bare == "[redacted]camera"
    assert "secret" not in bare


def test_non_string_and_blank_values_use_the_fallback() -> None:
    assert sanitize_display_text(None, fallback="Unknown") == "Unknown"
    assert sanitize_display_text(42, fallback="Unknown") == "Unknown"
    assert sanitize_display_text("   ", fallback="Unknown") == "Unknown"


def test_long_values_are_bounded() -> None:
    text = sanitize_display_text("a" * 500, fallback="Unknown")
    assert len(text) <= MAX_TEXT_LENGTH
    assert text.endswith("…")


def test_sanitised_zone_name_is_used_in_the_message() -> None:
    message = render_event_message(
        EventType.PERSON_ENTERING,
        _context(zone_name="<b>Front</b>\x00 door"),
    )
    assert "<" not in message and ">" not in message
    assert "FrontbFront/b door" not in message
    assert "entering bFront/b door" in message


# --- time formatting -----------------------------------------------------------


def test_format_event_time_uses_explicit_utc() -> None:
    assert format_event_time(START) == "2026-10-29 12:00:00 UTC"


def test_format_event_time_converts_offset_times() -> None:
    plus_two = timezone(timedelta(hours=2))
    assert format_event_time(datetime(2026, 10, 29, 14, 0, tzinfo=plus_two)) == (
        "2026-10-29 12:00:00 UTC"
    )


def test_format_event_time_treats_naive_values_as_utc() -> None:
    assert format_event_time(datetime(2026, 10, 29, 12, 0, 0)) == ("2026-10-29 12:00:00 UTC")


def test_format_event_time_has_a_fallback() -> None:
    assert format_event_time(None) == FALLBACKS["event_time"]


# --- input validation ----------------------------------------------------------


def test_unknown_event_type_is_rejected() -> None:
    with pytest.raises(MessageRenderError, match="unknown event type"):
        render_event_message("made_up", _context())


def test_invalid_metadata_is_rejected() -> None:
    with pytest.raises(MessageRenderError, match="invalid message metadata"):
        render_event_message(EventType.CROWD_FORMING, {"occupancy_count": -1})
    with pytest.raises(MessageRenderError):
        render_event_message(EventType.PERSON_ENTERING, {"unknown_field": "x"})


def test_context_accepts_a_mapping() -> None:
    message = render_event_message(
        EventType.PERSON_ENTERING,
        {"camera_name": "Cam", "zone_name": "Hall", "event_time": START},
    )
    assert "Hall" in message and "Cam" in message


# --- snapshot adapter ----------------------------------------------------------


def _snapshot(**overrides: object) -> EventSnapshot:
    data: dict[str, object] = {
        "event_id": "evt-1",
        "camera_id": 1,
        "event_type": EventType.DOOR_OPEN_TOO_LONG,
        "zone_name": "Side door",
        "start_time": START,
        "trigger_time": START + timedelta(seconds=30),
        "last_updated_at": START + timedelta(seconds=30),
        "status": EventStatus.ACTIVE,
        "severity": EventSeverity.WARNING,
        "attributes": {"duration_seconds": 61, "threshold_seconds": 60},
    }
    data.update(overrides)
    return EventSnapshot.model_validate(data)


def test_message_context_is_built_from_snapshot_attributes() -> None:
    context = message_context_from_event(_snapshot(), camera_name="Cam")
    assert context.zone_name == "Side door"
    assert context.duration_seconds == 61.0
    assert context.threshold_seconds == 60.0
    assert context.event_time == START + timedelta(seconds=30)


def test_render_event_matches_direct_rendering() -> None:
    snapshot = _snapshot()
    assert render_event(snapshot, camera_name="Cam") == render_event_message(
        EventType.DOOR_OPEN_TOO_LONG,
        {
            "camera_name": "Cam",
            "zone_name": "Side door",
            "duration_seconds": 61,
            "threshold_seconds": 60,
            "event_time": START + timedelta(seconds=30),
        },
    )


def test_snapshot_adapter_ignores_invalid_attribute_types() -> None:
    context = message_context_from_event(
        _snapshot(attributes={"occupancy_count": "many", "duration_seconds": -4}),
        camera_name=None,
    )
    assert context.occupancy_count is None
    assert context.duration_seconds is None


def test_non_integer_occupancy_attribute_is_ignored() -> None:
    context = message_context_from_event(
        _snapshot(attributes={"occupancy_count": 2.5}), camera_name=None
    )
    assert context.occupancy_count is None
