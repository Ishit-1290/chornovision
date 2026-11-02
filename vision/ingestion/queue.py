"""Bounded, thread-safe per-camera frame queue (FR-07, NFR-04, NFR-05).

A camera's decoder can produce frames faster than detection consumes them (especially on
CPU-only inference). The queue is therefore **bounded**: when it is full the oldest frame is
dropped to keep latency low and memory flat, and the drop is counted so it is observable
(NFR-05). :attr:`FrameQueue.depth` and :attr:`FrameQueue.dropped` are reported in the
worker's metrics snapshot.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from enum import StrEnum
from typing import Any, TypeVar

T = TypeVar("T")


class DropPolicy(StrEnum):
    """What to do when a bounded queue is full."""

    #: Drop the oldest queued frame (keep recent data; lowest latency). Default.
    DROP_OLDEST = "drop_oldest"
    #: Drop the incoming frame (keep the earliest queued frames).
    DROP_NEWEST = "drop_newest"


class FrameQueue:
    """A bounded FIFO queue with an explicit drop policy."""

    def __init__(
        self,
        maxsize: int,
        *,
        policy: DropPolicy = DropPolicy.DROP_OLDEST,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self._maxsize = maxsize
        self._policy = policy
        self._clock = clock
        self._items: deque[Any] = deque()
        self._cond = threading.Condition()
        self._closed = False
        self._dropped = 0
        self._max_depth = 0
        self._last_activity = clock()

    def put(self, item: T) -> bool:
        """Enqueue ``item``. Returns ``False`` when the incoming frame was dropped."""
        with self._cond:
            if self._closed:
                return False
            stored = True
            if len(self._items) >= self._maxsize:
                self._dropped += 1
                if self._policy is DropPolicy.DROP_OLDEST:
                    self._items.popleft()
                else:
                    stored = False
            if stored:
                self._items.append(item)
                if len(self._items) > self._max_depth:
                    self._max_depth = len(self._items)
            self._last_activity = self._clock()
            self._cond.notify()
            return stored

    def get(self, timeout: float | None = None) -> Any | None:
        """Dequeue the oldest item, or ``None`` on timeout / after :meth:`close`."""
        with self._cond:
            if not self._items and not self._closed:
                self._cond.wait(timeout)
            if not self._items:
                return None
            item = self._items.popleft()
            self._last_activity = self._clock()
            return item

    def wake(self) -> None:
        """Wake any blocked :meth:`get` callers without changing the queue contents."""
        with self._cond:
            self._cond.notify_all()

    def close(self) -> None:
        """Mark the queue closed and wake every waiter."""
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def depth(self) -> int:
        with self._cond:
            return len(self._items)

    @property
    def maxsize(self) -> int:
        return self._maxsize

    @property
    def dropped(self) -> int:
        with self._cond:
            return self._dropped

    @property
    def max_depth(self) -> int:
        with self._cond:
            return self._max_depth

    @property
    def last_activity(self) -> float:
        with self._cond:
            return self._last_activity

    def __len__(self) -> int:
        return self.depth
