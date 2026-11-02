"""In-memory login rate limiting.

Deliberately dependency-free (no Redis) per ``workflow_requirements.md`` §17. State is
per-process and resets on restart, which is acceptable for the single-process academic
prototype. It records failed attempts per key within a rolling window.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from collections.abc import Callable
from time import monotonic


class LoginRateLimiter:
    """A fixed-window login attempt limiter keyed by an arbitrary string."""

    def __init__(
        self,
        max_attempts: int,
        window_seconds: float,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._max_attempts = max_attempts
        self._window = window_seconds
        self._clock = clock
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        events = self._events[key]
        cutoff = now - self._window
        while events and events[0] <= cutoff:
            events.popleft()
        if not events:
            self._events.pop(key, None)
        return events

    def allow(self, key: str) -> bool:
        """Return ``True`` if a login attempt for ``key`` is currently permitted."""
        now = self._clock()
        with self._lock:
            events = self._prune(key, now)
            return len(events) < self._max_attempts

    def record_failure(self, key: str) -> None:
        """Record a failed login attempt for ``key``."""
        now = self._clock()
        with self._lock:
            self._events[key].append(now)
            self._prune(key, now)

    def reset(self, key: str) -> None:
        """Clear the recorded failures for ``key`` (e.g. after a successful login)."""
        with self._lock:
            self._events.pop(key, None)

    def retry_after(self, key: str) -> int:
        """Seconds until the oldest recorded attempt leaves the window (>= 0)."""
        now = self._clock()
        with self._lock:
            events = self._prune(key, now)
            if not events:
                return 0
            remaining = self._window - (now - events[0])
            return max(0, int(remaining) + 1)


def login_rate_limit_key(client_host: str | None, username: str) -> str:
    """Build the limiter key from the client address and submitted username."""
    return f"{client_host or 'unknown'}|{username.strip().lower()}"
