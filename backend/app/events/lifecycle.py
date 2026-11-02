"""Event lifecycle state machine (FR-23, FR-24, D-07).

The legal states are exactly ``candidate``, ``active``, ``completed``, ``uncertain``
and ``cancelled``. ``completed`` and ``cancelled`` are terminal; an event that
reoccurs later is a new event with a new stable identity. ``uncertain`` is not
terminal because a rule may recover to ``active`` when observations become reliable
again (for example a door re-observed as open after a brief classifier outage).
"""

from __future__ import annotations

from app.events.types import EventStatus

#: Legal event lifecycle edges.
EVENT_TRANSITIONS: dict[EventStatus, frozenset[EventStatus]] = {
    EventStatus.CANDIDATE: frozenset(
        {EventStatus.ACTIVE, EventStatus.UNCERTAIN, EventStatus.CANCELLED}
    ),
    EventStatus.ACTIVE: frozenset(
        {EventStatus.COMPLETED, EventStatus.UNCERTAIN, EventStatus.CANCELLED}
    ),
    EventStatus.UNCERTAIN: frozenset(
        {
            EventStatus.ACTIVE,
            EventStatus.COMPLETED,
            EventStatus.CANCELLED,
            EventStatus.UNCERTAIN,
        }
    ),
    EventStatus.COMPLETED: frozenset(),
    EventStatus.CANCELLED: frozenset(),
}

TERMINAL_EVENT_STATES: frozenset[EventStatus] = frozenset(
    {EventStatus.COMPLETED, EventStatus.CANCELLED}
)


class InvalidEventTransition(ValueError):
    """An illegal event lifecycle transition was requested."""


def can_transition(current: EventStatus, target: EventStatus) -> bool:
    """Return ``True`` when ``current -> target`` is legal."""
    return target in EVENT_TRANSITIONS.get(current, frozenset())


def transition(current: EventStatus, target: EventStatus) -> EventStatus:
    """Validate and return ``target`` for an event moving from ``current``."""
    if not can_transition(current, target):
        raise InvalidEventTransition(
            f"illegal event transition from {current.value!r} to {target.value!r}"
        )
    return target
