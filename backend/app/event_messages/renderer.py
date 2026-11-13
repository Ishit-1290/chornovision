"""Deterministic message rendering (Phase 5; FR-30–FR-34).

The renderer is deliberately small and dependency-free apart from Pydantic:

1. validate the event type against the canonical set;
2. validate the supplied metadata types and ranges;
3. sanitise every dynamic text value (control characters, markup characters, raw
   stream URLs, embedded credentials);
4. interpolate the fixed template and return the final string.

No LLM, generative API, network call, or prompt is involved. The caller stores the
rendered message with the event; old messages are never regenerated when a template
changes (the stored string is authoritative for that event).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from datetime import datetime
from string import Formatter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.event_messages.templates import (
    ALLOWED_FIELDS,
    FALLBACKS,
    TEMPLATES,
    MessageTemplate,
)
from app.events.types import EventSnapshot, EventType, ensure_utc

#: Maximum length of an interpolated person-facing name. Camera names are already
#: bounded by the API schema; zones are bounded here as a defence in depth.
MAX_TEXT_LENGTH = 128

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")
#: Any ``scheme://...`` token is replaced wholesale, including any userinfo inside it.
_URL_TOKEN = re.compile(r"\b[A-Za-z][A-Za-z0-9+.\-]*://\S+")
#: ``user:password@host`` without a scheme.
_CREDENTIAL_TOKEN = re.compile(r"\b[^\s/@:]+:[^\s/@]+@")
_MARKUP_CHARS = re.compile(r"[<>]")


class MessageRenderError(ValueError):
    """The message could not be rendered from validated event data."""


class EventMessageContext(BaseModel):
    """Validated metadata used to render one event message."""

    model_config = ConfigDict(extra="forbid")

    camera_name: str | None = None
    zone_name: str | None = None
    occupancy_count: int | None = Field(default=None, ge=0)
    duration_seconds: float | None = Field(default=None, ge=0.0)
    threshold_seconds: float | None = Field(default=None, ge=0.0)
    event_time: datetime | None = None
    bed_zone_name: str | None = None


def _validate_templates() -> None:
    """Fail at import time if a template references an unknown placeholder."""
    formatter = Formatter()
    for event_type, message_template in TEMPLATES.items():
        for _literal, field_name, format_spec, conversion in formatter.parse(
            message_template.template
        ):
            if field_name is None:
                continue
            if field_name not in ALLOWED_FIELDS:
                raise RuntimeError(
                    f"template for {event_type.value!r} uses unknown field {field_name!r}"
                )
            if field_name not in message_template.fields:
                raise RuntimeError(
                    f"template for {event_type.value!r} omits {field_name!r} from fields"
                )
            if format_spec or conversion:
                raise RuntimeError(
                    f"template for {event_type.value!r} must not use format spec/conversion"
                )


_validate_templates()


def sanitize_display_text(value: Any, *, fallback: str, max_length: int = MAX_TEXT_LENGTH) -> str:
    """Return a safe, single-line display string.

    Untrusted values never reach the rendered message verbatim: control characters and
    angle brackets are removed, URL-like tokens (which could contain a camera stream
    reference and credentials) are redacted, and the length is bounded.
    """
    if not isinstance(value, str):
        return fallback
    text = unicodedata.normalize("NFKC", value)
    text = _CONTROL_CHARS.sub(" ", text)
    text = _URL_TOKEN.sub("[redacted-url]", text)
    text = _CREDENTIAL_TOKEN.sub("[redacted]", text)
    text = _MARKUP_CHARS.sub("", text)
    text = " ".join(text.split())
    if not text:
        return fallback
    if len(text) > max_length:
        text = text[: max_length - 1].rstrip() + "…"
    return text


def format_event_time(value: datetime | None) -> str:
    """Format an event time consistently in UTC, with an explicit time basis."""
    if value is None:
        return FALLBACKS["event_time"]
    return ensure_utc(value).strftime("%Y-%m-%d %H:%M:%S UTC")


def _whole_seconds(value: float | None, field: str) -> str:
    if value is None:
        return FALLBACKS[field]
    return str(max(0, int(round(value))))


def _values(context: EventMessageContext) -> dict[str, str]:
    zone_name = sanitize_display_text(context.zone_name, fallback=FALLBACKS["zone_name"])
    bed_zone_name = sanitize_display_text(
        context.bed_zone_name if context.bed_zone_name is not None else context.zone_name,
        fallback=FALLBACKS["bed_zone_name"],
    )
    return {
        "camera_name": sanitize_display_text(
            context.camera_name, fallback=FALLBACKS["camera_name"]
        ),
        "zone_name": zone_name,
        "occupancy_count": (
            FALLBACKS["occupancy_count"]
            if context.occupancy_count is None
            else str(context.occupancy_count)
        ),
        "duration": _whole_seconds(context.duration_seconds, "duration"),
        "threshold_seconds": _whole_seconds(context.threshold_seconds, "threshold_seconds"),
        "event_time": format_event_time(context.event_time),
        "bed_zone_name": bed_zone_name,
    }


def render_event_message(
    event_type: EventType | str,
    context: EventMessageContext | Mapping[str, Any] | None = None,
) -> str:
    """Render the fixed message for ``event_type`` from validated metadata."""
    try:
        resolved_type = EventType(event_type)
    except ValueError as exc:
        raise MessageRenderError(f"unknown event type {event_type!r}") from exc

    message_template: MessageTemplate = TEMPLATES[resolved_type]
    if context is None:
        validated = EventMessageContext()
    elif isinstance(context, EventMessageContext):
        validated = context
    else:
        try:
            validated = EventMessageContext.model_validate(context)
        except Exception as exc:  # pydantic ValidationError
            raise MessageRenderError(f"invalid message metadata: {exc}") from exc

    values = _values(validated)
    return message_template.template.format_map(values)


def message_context_from_event(
    event: EventSnapshot, *, camera_name: str | None
) -> EventMessageContext:
    """Build renderer metadata from a structured event snapshot."""
    attributes = event.attributes or {}
    return EventMessageContext(
        camera_name=camera_name,
        zone_name=event.zone_name,
        occupancy_count=_optional_int(attributes.get("occupancy_count")),
        duration_seconds=_optional_float(attributes.get("duration_seconds")),
        threshold_seconds=_optional_float(attributes.get("threshold_seconds")),
        event_time=event.trigger_time,
        bed_zone_name=_optional_str(attributes.get("bed_zone_name")) or event.zone_name,
    )


def render_event(event: EventSnapshot, *, camera_name: str | None) -> str:
    """Render the stored message for a structured event."""
    return render_event_message(
        event.event_type, message_context_from_event(event, camera_name=camera_name)
    )


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    return int(value) if value >= 0 else None


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value >= 0 else None


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
