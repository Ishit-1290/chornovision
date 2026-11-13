"""Per-camera lifecycle state machine (FR-03, ``../guidelines.md`` §6).

Pure, side-effect-free transitions so they can be unit-tested without a database or a
worker. The vision worker drives ``connecting → active``/``disconnected`` etc. (Phase 4),
while the monitoring control plane drives ``configured``/``stopped`` ↔ ``connecting``.

Semantic note (FR-05): ``DISCONNECTED`` means the stream is unavailable. It is a
stream-health state, never "connected but no activity", and there is deliberately no
direct ``DISCONNECTED → ACTIVE`` edge — recovery must pass through
``RECONNECTING``/``CONNECTING`` so that a tracking reset/recovery policy is applied.
"""

from __future__ import annotations

from app.models.camera import CameraStatus


class InvalidStateTransition(Exception):
    """Raised when a requested camera lifecycle transition is not permitted."""

    def __init__(self, current: CameraStatus, target: CameraStatus) -> None:
        self.current = current
        self.target = target
        super().__init__(f"invalid camera transition from {current.value!r} to {target.value!r}")


#: Legal edges of the per-camera lifecycle graph. Every state appears as a key.
LEGAL_TRANSITIONS: dict[CameraStatus, frozenset[CameraStatus]] = {
    CameraStatus.CONFIGURED: frozenset(
        {CameraStatus.CONNECTING, CameraStatus.STOPPED, CameraStatus.FAILED}
    ),
    CameraStatus.CONNECTING: frozenset(
        {
            CameraStatus.ACTIVE,
            CameraStatus.DISCONNECTED,
            CameraStatus.FAILED,
            CameraStatus.STOPPED,
        }
    ),
    CameraStatus.ACTIVE: frozenset(
        {
            CameraStatus.DEGRADED,
            CameraStatus.DISCONNECTED,
            CameraStatus.RECONNECTING,
            CameraStatus.STOPPED,
            CameraStatus.FAILED,
        }
    ),
    CameraStatus.DEGRADED: frozenset(
        {
            CameraStatus.ACTIVE,
            CameraStatus.DISCONNECTED,
            CameraStatus.RECONNECTING,
            CameraStatus.STOPPED,
            CameraStatus.FAILED,
        }
    ),
    CameraStatus.DISCONNECTED: frozenset(
        {
            CameraStatus.RECONNECTING,
            CameraStatus.CONNECTING,
            CameraStatus.STOPPED,
            CameraStatus.FAILED,
        }
    ),
    CameraStatus.RECONNECTING: frozenset(
        {
            CameraStatus.CONNECTING,
            CameraStatus.ACTIVE,
            CameraStatus.DISCONNECTED,
            CameraStatus.STOPPED,
            CameraStatus.FAILED,
        }
    ),
    CameraStatus.STOPPED: frozenset({CameraStatus.CONNECTING, CameraStatus.CONFIGURED}),
    CameraStatus.FAILED: frozenset({CameraStatus.CONNECTING, CameraStatus.STOPPED}),
}

#: States in which the runtime believes it is (or is becoming) connected/processing.
PROCESSING_STATES: frozenset[CameraStatus] = frozenset(
    {
        CameraStatus.CONNECTING,
        CameraStatus.ACTIVE,
        CameraStatus.DEGRADED,
        CameraStatus.DISCONNECTED,
        CameraStatus.RECONNECTING,
        CameraStatus.FAILED,
    }
)

#: States a camera may be started into from (its processing is not already underway).
STARTABLE_STATES: frozenset[CameraStatus] = frozenset(
    {CameraStatus.CONFIGURED, CameraStatus.STOPPED}
)


def coerce_status(value: str | CameraStatus) -> CameraStatus:
    """Return ``value`` as a :class:`CameraStatus`, or raise :class:`ValueError`."""
    if isinstance(value, CameraStatus):
        return value
    return CameraStatus(value)


def can_transition(current: str | CameraStatus, target: str | CameraStatus) -> bool:
    """Return ``True`` if ``current → target`` is a legal lifecycle transition."""
    source = coerce_status(current)
    destination = coerce_status(target)
    return destination in LEGAL_TRANSITIONS[source]


def transition(current: str | CameraStatus, target: str | CameraStatus) -> CameraStatus:
    """Validate and return ``target``, raising :class:`InvalidStateTransition` if illegal."""
    source = coerce_status(current)
    destination = coerce_status(target)
    if destination not in LEGAL_TRANSITIONS[source]:
        raise InvalidStateTransition(source, destination)
    return destination
