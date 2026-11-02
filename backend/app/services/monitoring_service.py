"""Global monitoring control plane and per-camera state reconciliation (FR-47, W §10).

Monitoring is a single, process-level control (start/pause/stop/status) that is
independent of any browser session: logging out does not stop monitoring (W §3.4).

The control plane owns the *requested* monitoring state; the Phase 4 vision worker owns
*runtime* health. ``start`` moves enabled cameras to ``CONNECTING`` and never claims
``ACTIVE``: only the worker's ``/api/internal`` state report may do that (D-24). When a
camera is in a processing state but its worker has stopped reporting (a dead worker or
process), :func:`effective_status` projects it as ``DISCONNECTED`` at read time, so health
reporting stays truthful without a per-request background task.

The monitoring flag is intentionally in-memory. On restart it is ``STOPPED``, which is the
correct state because no worker survives the restart; camera lifecycle rows are reconciled by
the worker (``POST /api/internal/reconcile``) rather than by the API process.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.camera import Camera, CameraStatus
from app.repositories import cameras as cameras_repo
from app.schemas.monitoring import MonitoringCameraState, MonitoringStatusResponse
from app.services import lifecycle
from app.services.worker_registry import get_worker_registry
from app.utils import ensure_utc, utcnow

#: String values of the states in which a worker is (becoming) connected/processing.
_PROCESSING_VALUES: frozenset[str] = frozenset(
    status.value for status in lifecycle.PROCESSING_STATES
)


class MonitoringState(StrEnum):
    """Global monitoring control states."""

    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


class InvalidMonitoringTransition(Exception):
    """Raised when a monitoring command is not legal from the current state."""

    def __init__(self, current: MonitoringState, command: str) -> None:
        self.current = current
        self.command = command
        super().__init__(f"cannot {command} monitoring while it is {current.value!r}")


@dataclass(frozen=True)
class MonitoringResult:
    """Outcome of a monitoring command."""

    state: MonitoringState
    affected: int


class MonitoringController:
    """Thread-safe global monitoring state machine (no database access)."""

    def __init__(self) -> None:
        self._state = MonitoringState.STOPPED
        self._lock = threading.Lock()

    @property
    def state(self) -> MonitoringState:
        with self._lock:
            return self._state

    def start(self) -> MonitoringState:
        """Start or resume monitoring. Idempotent while already running."""
        with self._lock:
            if self._state is MonitoringState.RUNNING:
                return self._state
            self._state = MonitoringState.RUNNING
            return self._state

    def pause(self) -> MonitoringState:
        """Pause a running monitoring session. Idempotent while already paused."""
        with self._lock:
            if self._state is MonitoringState.PAUSED:
                return self._state
            if self._state is not MonitoringState.RUNNING:
                raise InvalidMonitoringTransition(self._state, "pause")
            self._state = MonitoringState.PAUSED
            return self._state

    def stop(self) -> MonitoringState:
        """Stop monitoring from any state. Idempotent."""
        with self._lock:
            self._state = MonitoringState.STOPPED
            return self._state


_controller: MonitoringController | None = None
_controller_lock = threading.Lock()


def get_monitoring_controller() -> MonitoringController:
    """Return the process-wide monitoring controller (created on first use)."""
    global _controller
    if _controller is None:
        with _controller_lock:
            if _controller is None:
                _controller = MonitoringController()
    return _controller


def reset_monitoring_controller() -> None:
    """Drop the cached controller (used by tests)."""
    global _controller
    _controller = None


def _transition_cameras(
    db: Session, source: set[CameraStatus], target: CameraStatus, *, only_enabled: bool
) -> int:
    affected = 0
    for camera in cameras_repo.list_by_statuses(db, source):
        if only_enabled and not camera.enabled:
            continue
        camera.status = lifecycle.transition(camera.status, target).value
        affected += 1
    if affected:
        db.commit()
    return affected


def start_monitoring(db: Session) -> MonitoringResult:
    """Start monitoring and move startable enabled cameras to ``connecting``."""
    state = get_monitoring_controller().start()
    affected = _transition_cameras(
        db, set(lifecycle.STARTABLE_STATES), CameraStatus.CONNECTING, only_enabled=True
    )
    return MonitoringResult(state=state, affected=affected)


def pause_monitoring(db: Session) -> MonitoringResult:
    """Pause monitoring and stop active cameras (configuration is retained)."""
    state = get_monitoring_controller().pause()
    affected = _transition_cameras(
        db, set(lifecycle.PROCESSING_STATES), CameraStatus.STOPPED, only_enabled=False
    )
    return MonitoringResult(state=state, affected=affected)


def stop_monitoring(db: Session) -> MonitoringResult:
    """Stop monitoring and stop every processing camera."""
    state = get_monitoring_controller().stop()
    affected = _transition_cameras(
        db, set(lifecycle.PROCESSING_STATES), CameraStatus.STOPPED, only_enabled=False
    )
    return MonitoringResult(state=state, affected=affected)


def effective_status(camera: Camera, *, now: datetime | None = None) -> str:
    """Return the camera's lifecycle state, projecting a stale worker as ``disconnected``.

    A camera in a processing state whose worker has neither reported nor changed state within
    ``WORKER_HEARTBEAT_TIMEOUT_SECONDS`` is reported as ``disconnected``. This is a read-time
    projection only: the persisted row is left untouched so the worker (or an operator) can
    correct it. Non-processing states are returned unchanged.
    """
    status = camera.status
    if status not in _PROCESSING_VALUES:
        return status

    moment = now or utcnow()
    timeout = timedelta(seconds=get_settings().worker_heartbeat_timeout_seconds)
    candidates: list[datetime] = []
    report = get_worker_registry().get(camera.id)
    if report is not None:
        candidates.append(ensure_utc(report.reported_at))
    if camera.updated_at is not None:
        candidates.append(ensure_utc(camera.updated_at))
    if not candidates:
        return status
    if moment - max(candidates) > timeout:
        return CameraStatus.DISCONNECTED.value
    return status


def monitoring_snapshot(db: Session) -> MonitoringStatusResponse:
    """Return the global monitoring state and each camera's effective lifecycle state."""
    state = get_monitoring_controller().state
    cameras: list[Camera] = cameras_repo.list_all(db)
    projected = [(camera, effective_status(camera)) for camera in cameras]
    counts: dict[str, int] = {}
    for _camera, status in projected:
        counts[status] = counts.get(status, 0) + 1
    return MonitoringStatusResponse(
        state=state.value,
        running=state is MonitoringState.RUNNING,
        counts=counts,
        cameras=[
            MonitoringCameraState(
                id=camera.id, name=camera.name, enabled=camera.enabled, status=status
            )
            for camera, status in projected
        ],
    )
