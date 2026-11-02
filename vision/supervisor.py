"""Supervisor: reconcile local workers against the backend's requested state (FR-47).

The supervisor is the worker process's control loop. It polls the backend internal API for
the *requested* monitoring state and the enabled cameras, then asks the
:class:`~vision.camera_manager.manager.CameraManager` to converge to that target:

* monitoring not ``running``  → no workers run;
* monitoring ``running``      → enabled cameras have a live worker.

It never opens a network connection to a camera itself and never runs inference in an HTTP
handler; it only owns the worker set. A backend that is temporarily unreachable is logged and
retried on the next poll, leaving the current worker set untouched.
"""

from __future__ import annotations

import logging
import threading

from vision.camera_manager.manager import CameraManager
from vision.camera_manager.worker import CameraConfig
from vision.config import VisionSettings
from vision.internal_client import InternalClient, InternalClientError

LOGGER = logging.getLogger("vision.supervisor")


class Supervisor:
    """Polls the backend plan and reconciles the local worker set."""

    def __init__(
        self,
        *,
        client: InternalClient,
        settings: VisionSettings,
        manager: CameraManager,
        logger: logging.Logger | None = None,
    ) -> None:
        self._client = client
        self._settings = settings
        self._manager = manager
        self._logger = logger or LOGGER

    @property
    def manager(self) -> CameraManager:
        return self._manager

    def reconcile(self) -> None:
        """Converge the worker set to the backend's requested plan (best effort)."""
        try:
            plan = self._client.fetch_plan()
        except InternalClientError as exc:
            self._logger.warning("could not fetch runtime plan: %s", exc)
            return
        if not plan.running:
            self._manager.ensure([])
            return
        cameras = [
            CameraConfig(
                id=camera.id,
                name=camera.name,
                stream_reference=camera.stream_reference,
                enabled=camera.enabled,
                configuration=camera.configuration,
            )
            for camera in plan.enabled_cameras()
        ]
        self._manager.ensure(cameras)

    def run(self, stop_event: threading.Event) -> None:
        """Poll until ``stop_event`` is set."""
        while not stop_event.wait(self._settings.poll_interval_seconds):
            self.reconcile()

    def shutdown(self) -> None:
        """Stop every worker."""
        self._manager.shutdown()
