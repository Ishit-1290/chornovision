"""Per-camera evidence + event-handoff coordinator (Phase 6; FR-36, FR-40).

The event engine publishes synchronously on the worker's frame thread, so the coordinator's
``publish`` only performs bounded, non-blocking bookkeeping:

1. the transition is enqueued for authenticated delivery to the backend (bounded in-memory
   queue, with a bounded on-disk spool when the queue is full);
2. the evidence manager records that a capture window has opened.

Encoding, filesystem writes, and network delivery all happen on background threads owned by
the manager/handoff. The coordinator also forwards processed frames into open capture windows,
finalises them at stream end/reconnect, and merges counters for worker health metrics.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from app.events.types import EventTransition

from vision.evidence.manager import EvidenceManager

if TYPE_CHECKING:  # avoid a circular import: event_handoff imports the evidence store
    from vision.event_handoff import EventHandoff

LOGGER = logging.getLogger("vision.evidence.coordinator")


class EvidenceCoordinator:
    """Connects the event engine to bounded persistence and evidence capture."""

    def __init__(
        self,
        *,
        camera_id: int,
        manager: EvidenceManager,
        handoff: EventHandoff,
        clock: Callable[[], float] = time.monotonic,
        logger: logging.Logger | None = None,
    ) -> None:
        self._camera_id = camera_id
        self._manager = manager
        self._handoff = handoff
        self._clock = clock
        self._logger = logger or LOGGER

    @property
    def camera_id(self) -> int:
        return self._camera_id

    # -- lifecycle -----------------------------------------------------------------
    def start(self) -> None:
        """Ensure the delivery and encoder threads are running (idempotent)."""
        self._handoff.start()
        self._manager.start()

    def shutdown(self, timeout: float = 5.0) -> None:
        """Finalise captures, deliver what is possible, and spill the rest durably."""
        # Finalise + encode before stopping delivery so the evidence records can be sent.
        self._manager.shutdown(timeout=timeout)
        self._handoff.shutdown(timeout=timeout)

    # -- EventSink -----------------------------------------------------------------
    def publish(self, transition: EventTransition) -> None:
        """Accept one transition without blocking the frame loop."""
        try:
            # Event first: the backend must know the event before evidence references it.
            self._handoff.enqueue_event(transition)
        except Exception:  # pragma: no cover - enqueue is defensive, but never crash the loop
            self._logger.warning(
                "camera %s: could not hand off event %s",
                self._camera_id,
                transition.event.event_id,
                exc_info=True,
            )
        self._manager.handle_transition(transition, self._clock())

    # -- frame / session input -----------------------------------------------------
    def bind_buffer(self, buffer: Any) -> None:
        """Use the worker's bounded rolling buffer for pre-event frames."""
        self._manager.bind_buffer(buffer)

    def on_frame(self, frame: Any, monotonic: float | None = None) -> None:
        """Record one processed frame in every open capture window."""
        self._manager.on_frame(frame, self._clock() if monotonic is None else monotonic)

    def on_stream_end(self, monotonic: float | None = None) -> None:
        """Finalise every open capture when the stream session ends."""
        self._manager.on_stream_end(self._clock() if monotonic is None else monotonic)

    def reset(self) -> None:
        """Finalise captures before a reconnect clears the frame buffer."""
        self._manager.reset()

    # -- introspection -------------------------------------------------------------
    def counters(self) -> dict[str, int]:
        """Merged manager + handoff counters for worker health reports."""
        merged = {
            key if key.startswith("evidence_") else f"evidence_{key}": value
            for key, value in self._manager.counters().items()
        }
        merged.update({f"handoff_{key}": value for key, value in self._handoff.counters().items()})
        merged["evidence_active_captures"] = self._manager.active_captures
        return merged
