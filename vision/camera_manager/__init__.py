"""Camera manager: explicit, testable ownership of camera workers (FR-02, W §3.4).

The manager is the single owner of :class:`~vision.camera_manager.worker.CameraWorker`
instances. It never creates a worker implicitly: :meth:`CameraManager.ensure` starts workers
for the requested cameras (up to a configured concurrency) and stops workers for cameras that
are no longer requested. Only one camera is started in Phase 4 (CON-08); multi-camera process
isolation is Phase 8 work.
"""

from __future__ import annotations

__all__: list[str] = []
