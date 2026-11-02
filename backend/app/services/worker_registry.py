"""In-memory worker-health registry (Phase 4).

The vision worker reports lifecycle state to the backend over the internal HTTP channel
(OQ-09 / D-12). This registry records the **most recent report per camera** so that:

* the control plane can project a camera as ``disconnected`` when its worker stops
  heartbeating (a dead worker/process), without any per-request background task; and
* the worker's non-sensitive metrics are available for health reporting.

It is deliberately in-memory: it describes the *current* runtime, is rebuilt from worker
reports after a restart, and never persists anything sensitive. Nothing here is exposed by an
unauthenticated endpoint except the projected lifecycle state.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.utils import utcnow


@dataclass(frozen=True)
class WorkerReport:
    """The last report received from a camera worker."""

    camera_id: int
    status: str
    detail: str | None
    metrics: dict[str, object] | None
    reported_at: datetime


class WorkerHealthRegistry:
    """Thread-safe ``camera_id -> last report`` map."""

    def __init__(self, *, clock: Callable[[], datetime] = utcnow) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._reports: dict[int, WorkerReport] = {}

    def record(
        self,
        camera_id: int,
        status: str,
        *,
        detail: str | None = None,
        metrics: dict[str, object] | None = None,
    ) -> WorkerReport:
        report = WorkerReport(
            camera_id=camera_id,
            status=status,
            detail=detail,
            metrics=dict(metrics) if metrics is not None else None,
            reported_at=self._clock(),
        )
        with self._lock:
            self._reports[camera_id] = report
        return report

    def get(self, camera_id: int) -> WorkerReport | None:
        with self._lock:
            return self._reports.get(camera_id)

    def last_seen(self, camera_id: int) -> datetime | None:
        report = self.get(camera_id)
        return report.reported_at if report is not None else None

    def forget(self, camera_id: int) -> None:
        with self._lock:
            self._reports.pop(camera_id, None)

    def clear(self) -> None:
        with self._lock:
            self._reports.clear()

    def snapshot(self) -> dict[int, WorkerReport]:
        with self._lock:
            return dict(self._reports)


_registry: WorkerHealthRegistry | None = None
_registry_lock = threading.Lock()


def get_worker_registry() -> WorkerHealthRegistry:
    """Return the process-wide registry (created on first use)."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = WorkerHealthRegistry()
    return _registry


def reset_worker_registry() -> None:
    """Drop the cached registry (used by tests)."""
    global _registry
    _registry = None
