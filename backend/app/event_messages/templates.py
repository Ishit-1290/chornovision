"""Deterministic event message templates (Phase 5; FR-30–FR-34, W §8).

Every template is a fixed Python format string. There is no LLM, no external text
generation service, and no prompt anywhere in this package. The event engine selects
the template by the canonical ``event_type``; the renderer validates and sanitises
metadata before interpolating it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.events.types import EventType


@dataclass(frozen=True)
class MessageTemplate:
    """A fixed message template and the fields it requires."""

    event_type: EventType
    template: str
    fields: tuple[str, ...]


#: The seven activity templates from ``../workflow_requirements.md`` §8, plus the
#: distinct ``room_occupancy_change`` wording required by the two-category occupancy
#: decision (D-10/D-36). Wording is fixed and must only change by a documented change.
TEMPLATES: dict[EventType, MessageTemplate] = {
    EventType.PERSON_ENTERING: MessageTemplate(
        event_type=EventType.PERSON_ENTERING,
        template=("Person detected entering {zone_name} on camera {camera_name} at {event_time}."),
        fields=("zone_name", "camera_name", "event_time"),
    ),
    EventType.PERSON_LEAVING: MessageTemplate(
        event_type=EventType.PERSON_LEAVING,
        template=("Person detected leaving {zone_name} on camera {camera_name} at {event_time}."),
        fields=("zone_name", "camera_name", "event_time"),
    ),
    EventType.ROOM_OCCUPANCY_CHANGE: MessageTemplate(
        event_type=EventType.ROOM_OCCUPANCY_CHANGE,
        template=(
            "Occupancy update in {zone_name} on camera {camera_name}. "
            "Detected occupancy: {occupancy_count} people at {event_time}."
        ),
        fields=("zone_name", "camera_name", "occupancy_count", "event_time"),
    ),
    EventType.CROWD_FORMING: MessageTemplate(
        event_type=EventType.CROWD_FORMING,
        template=(
            "Occupancy threshold reached in {zone_name} on camera {camera_name}. "
            "Detected occupancy: {occupancy_count} people at {event_time}."
        ),
        fields=("zone_name", "camera_name", "occupancy_count", "event_time"),
    ),
    EventType.DOOR_OPEN_TOO_LONG: MessageTemplate(
        event_type=EventType.DOOR_OPEN_TOO_LONG,
        template=(
            "Door at {zone_name} has remained open for {duration} seconds on camera "
            "{camera_name}. Threshold: {threshold_seconds} seconds."
        ),
        fields=("zone_name", "duration", "camera_name", "threshold_seconds"),
    ),
    EventType.PACKAGE_LEFT_AT_ENTRANCE: MessageTemplate(
        event_type=EventType.PACKAGE_LEFT_AT_ENTRANCE,
        template=(
            "A package appears to have been left unattended in {zone_name} on camera "
            "{camera_name} for {duration} seconds."
        ),
        fields=("zone_name", "camera_name", "duration"),
    ),
    EventType.PERSON_MOTIONLESS: MessageTemplate(
        event_type=EventType.PERSON_MOTIONLESS,
        template=(
            "A person has shown limited detectable movement for {duration} seconds in "
            "{zone_name} on camera {camera_name}. Review the evidence to confirm the "
            "situation."
        ),
        fields=("duration", "zone_name", "camera_name"),
    ),
    EventType.FALL_FROM_BED: MessageTemplate(
        event_type=EventType.FALL_FROM_BED,
        template=(
            "Potential fall detected near {bed_zone_name} on camera {camera_name} at "
            "{event_time}. Review the evidence to assess the event."
        ),
        fields=("bed_zone_name", "camera_name", "event_time"),
    ),
}

#: Safe fallback values when metadata is missing (W §8).
FALLBACKS: dict[str, str] = {
    "camera_name": "Unknown",
    "zone_name": "Unknown zone",
    "occupancy_count": "an unknown number of",
    "duration": "an unknown number of",
    "threshold_seconds": "an unknown number of",
    "event_time": "an unknown time",
    "bed_zone_name": "the bed area",
}

#: Placeholders that may appear in a template. Anything else is a programming error,
#: not a user-input condition.
ALLOWED_FIELDS: frozenset[str] = frozenset(FALLBACKS)


def template_for(event_type: EventType) -> MessageTemplate:
    """Return the fixed template for ``event_type``."""
    return TEMPLATES[event_type]
