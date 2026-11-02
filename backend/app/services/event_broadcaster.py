"""In-process fan-out for dashboard WebSocket notifications (Phase 7; FR-48).

The dashboard is a *consumer* of the persisted state, never the source of truth. This
broadcaster therefore only carries lightweight notifications (an event changed, a camera's
lifecycle state changed, monitoring started/stopped); the browser then re-reads authorized
details through the normal REST API (``docs/ARCHITECTURE.md`` §3.13). That keeps the event
and camera data behind the same session authorization as every other endpoint and keeps the
WebSocket payload free of evidence bytes, stream references, or credentials.

Design constraints:

* Publishing happens from synchronous FastAPI handlers (worker→backend internal routes and
  user commands), while subscriptions live on the asyncio event loop of the WebSocket
  handler. :meth:`EventBroadcaster.publish` is therefore thread-safe and schedules delivery
  with ``loop.call_soon_threadsafe``.
* Each subscriber has a **bounded** queue. A slow/stuck browser can never grow memory
  without bound: the oldest undelivered notification is dropped instead.
* This is deliberately in-process (single uvicorn worker). Horizontal scaling would need a
  shared bus; that limitation is documented rather than pretended away.
"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Any

from app.utils import ensure_utc

if TYPE_CHECKING:
    from app.models.event import Event

#: Maximum notifications buffered for one slow subscriber before the oldest is dropped.
DEFAULT_QUEUE_MAXSIZE = 256


def event_notification(event: Event) -> dict[str, Any]:
    """Build the lightweight notification for a persisted event change.

    Carries only identifiers and display-safe fields; evidence bytes, attributes, and
    stream references are fetched through the authorized REST endpoints instead.
    """
    return {
        "type": "event",
        "event": {
            "id": event.id,
            "event_id": event.event_id,
            "camera_id": event.camera_id,
            "event_type": event.event_type,
            "status": event.status,
            "review_status": event.review_status,
            "trigger_time": ensure_utc(event.trigger_time).isoformat(),
            "message": event.message,
        },
    }


def camera_notification(camera_id: int, status: str) -> dict[str, Any]:
    """Build the lightweight notification for a camera lifecycle-state change."""
    return {"type": "camera", "camera": {"id": camera_id, "status": status}}


def _enqueue(queue: asyncio.Queue, message: dict[str, Any]) -> None:
    """Put ``message`` on ``queue``, dropping the oldest item if it is full."""
    try:
        queue.put_nowait(message)
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
            queue.put_nowait(message)
        except (asyncio.QueueEmpty, asyncio.QueueFull):  # pragma: no cover - defensive
            pass


class EventBroadcaster:
    """Thread-safe registry of WebSocket subscriber queues."""

    def __init__(self, *, queue_maxsize: int = DEFAULT_QUEUE_MAXSIZE) -> None:
        self._queue_maxsize = queue_maxsize
        self._lock = threading.Lock()
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Remember the loop that owns the subscriber queues (called on connect)."""
        with self._lock:
            self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        """Create and register a bounded queue.

        Must be called from within the asyncio loop that will consume it.
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._queue_maxsize)
        with self._lock:
            self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Remove a subscriber (idempotent)."""
        with self._lock:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        """Number of currently connected dashboard subscribers."""
        with self._lock:
            return len(self._subscribers)

    def publish(self, message: dict[str, Any]) -> None:
        """Fan a notification out to every subscriber (thread-safe, never raises).

        With no bound loop or no subscribers this is a cheap no-op, so callers can publish
        unconditionally from request handlers.
        """
        with self._lock:
            loop = self._loop
            subscribers = tuple(self._subscribers)
        if loop is None or not subscribers:
            return
        for queue in subscribers:
            try:
                loop.call_soon_threadsafe(_enqueue, queue, message)
            except RuntimeError:
                # The loop is shutting down; drop the notification rather than fail the
                # request that produced it.
                return


_broadcaster: EventBroadcaster | None = None
_broadcaster_lock = threading.Lock()


def get_event_broadcaster() -> EventBroadcaster:
    """Return the process-wide broadcaster (created on first use)."""
    global _broadcaster
    if _broadcaster is None:
        with _broadcaster_lock:
            if _broadcaster is None:
                _broadcaster = EventBroadcaster()
    return _broadcaster


def reset_event_broadcaster() -> None:
    """Drop the cached broadcaster (used by tests)."""
    global _broadcaster
    _broadcaster = None
