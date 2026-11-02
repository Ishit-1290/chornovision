"""Ownership and concurrency for camera workers (FR-02, NFR-02).

:class:`CameraManager` is the only place that starts or stops workers. ``ensure`` is
declarative: it is given the cameras that *should* be running and converges the set of live
workers to that target, starting at most ``max_concurrent`` workers (one camera in Phase 4,
CON-08). All mutations are guarded by a lock so the supervisor and shutdown path cannot
interleave.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence

from vision.camera_manager.worker import CameraConfig, CameraWorker
from vision.health import WorkerHealth

LOGGER = logging.getLogger("vision.camera_manager")

WorkerFactory = Callable[[CameraConfig], CameraWorker]


class CameraManager:
    """Owns the live set of camera workers."""

    def __init__(
        self,
        *,
        worker_factory: WorkerFactory,
        max_concurrent: int = 1,
        stop_timeout: float = 10.0,
        logger: logging.Logger | None = None,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        self._worker_factory = worker_factory
        self._max_concurrent = max_concurrent
        self._stop_timeout = stop_timeout
        self._logger = logger or LOGGER
        self._workers: dict[int, CameraWorker] = {}
        self._lock = threading.RLock()

    def ensure(self, cameras: Sequence[CameraConfig]) -> None:
        """Start workers for ``cameras`` and stop any worker no longer requested.

        ``max_concurrent`` limits how many workers run at once. Cameras beyond the limit are
        left stopped rather than silently over-subscribing the machine. A camera whose
        configuration changed since its worker started is stopped and recreated so edited
        zones/rules take effect (a fresh worker also resets tracking and the event engine,
        FR-08).
        """
        with self._lock:
            desired = {camera.id: camera for camera in cameras}
            # Stop workers that are no longer desired, whose thread has died, or whose
            # configuration changed (an edited camera must not keep running stale rules).
            for camera_id in list(self._workers):
                worker = self._workers[camera_id]
                if (
                    camera_id not in desired
                    or not worker.is_alive()
                    or worker.config != desired[camera_id]
                ):
                    self._stop_locked(camera_id)

            for camera_id, camera in desired.items():
                if camera_id in self._workers:
                    continue
                if len(self._workers) >= self._max_concurrent:
                    self._logger.warning(
                        "camera %s deferred: max_concurrent=%d reached",
                        camera_id,
                        self._max_concurrent,
                    )
                    continue
                worker = self._worker_factory(camera)
                self._workers[camera_id] = worker
                worker.start()
                self._logger.info("camera %s: worker started", camera_id)

    def stop(self, camera_id: int) -> None:
        """Stop and forget a single camera worker."""
        with self._lock:
            self._stop_locked(camera_id)

    def stop_all(self) -> None:
        """Stop and forget every camera worker."""
        with self._lock:
            for camera_id in list(self._workers):
                self._stop_locked(camera_id)

    def _stop_locked(self, camera_id: int) -> None:
        worker = self._workers.pop(camera_id, None)
        if worker is None:
            return
        try:
            worker.stop(timeout=self._stop_timeout)
        except Exception:  # pragma: no cover - shutdown must not raise
            self._logger.exception("camera %s: error while stopping worker", camera_id)
        self._logger.info("camera %s: worker stopped", camera_id)

    def running_ids(self) -> list[int]:
        with self._lock:
            return sorted(self._workers)

    def health(self) -> list[WorkerHealth]:
        with self._lock:
            workers = list(self._workers.values())
        return [worker.health() for worker in workers]

    def shutdown(self) -> None:
        """Stop every worker (used on process shutdown)."""
        self.stop_all()
