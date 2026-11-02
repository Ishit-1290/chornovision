"""Bounded rolling frame buffer skeleton (FR-35, NFR-04).

Phase 6 will use this to capture pre-event frames. Phase 4 only maintains it so the
memory bound is real and testable from the start. The buffer is bounded by **both** a
maximum number of items and a maximum approximate byte budget; the oldest item is evicted
first. A single item larger than the byte budget is refused rather than stored, so memory
can never grow past the budget because of one oversized frame.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Iterable
from typing import Any


def _default_size(item: Any) -> int:
    """Best-effort size of ``item`` in bytes (0 when unknown)."""
    nbytes = getattr(item, "nbytes", None)
    if isinstance(nbytes, int):
        return nbytes
    image = getattr(item, "image", None)
    nbytes = getattr(image, "nbytes", None)
    if isinstance(nbytes, int):
        return nbytes
    return 0


class RollingFrameBuffer:
    """A bounded, oldest-first rolling buffer."""

    def __init__(
        self,
        max_items: int,
        max_bytes: int,
        *,
        size_of: Callable[[Any], int] = _default_size,
    ) -> None:
        if max_items < 1:
            raise ValueError("max_items must be >= 1")
        if max_bytes < 1:
            raise ValueError("max_bytes must be >= 1")
        self._max_items = max_items
        self._max_bytes = max_bytes
        self._size_of = size_of
        self._items: deque[Any] = deque()
        self._bytes = 0
        self._refused = 0

    def append(self, item: Any) -> bool:
        """Append ``item``, evicting the oldest entries as needed.

        Returns ``False`` (and increments :attr:`refused`) when the item alone exceeds the
        byte budget, in which case it is not stored.
        """
        size = max(0, int(self._size_of(item)))
        if size > self._max_bytes:
            self._refused += 1
            return False
        while self._items and (
            len(self._items) >= self._max_items or self._bytes + size > self._max_bytes
        ):
            self._evict_oldest()
        self._items.append(item)
        self._bytes += size
        return True

    def _evict_oldest(self) -> None:
        oldest = self._items.popleft()
        self._bytes -= max(0, int(self._size_of(oldest)))
        if self._bytes < 0:
            self._bytes = 0

    def clear(self) -> None:
        self._items.clear()
        self._bytes = 0

    def snapshot(self) -> list[Any]:
        """Return the buffered items oldest-first (a shallow copy)."""
        return list(self._items)

    def extend(self, items: Iterable[Any]) -> None:
        for item in items:
            self.append(item)

    def __len__(self) -> int:
        return len(self._items)

    @property
    def bytes_used(self) -> int:
        return self._bytes

    @property
    def max_items(self) -> int:
        return self._max_items

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def refused(self) -> int:
        return self._refused
