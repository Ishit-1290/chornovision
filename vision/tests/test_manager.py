"""Camera-manager ownership and concurrency tests (FR-02, NFR-02)."""

from __future__ import annotations

import pytest
from app.models.camera import CameraStatus

from vision.camera_manager.manager import CameraManager
from vision.camera_manager.worker import CameraConfig
from vision.health import WorkerHealth


class FakeWorker:
    def __init__(self, camera: CameraConfig) -> None:
        self.camera = camera
        self.started = False
        self.stopped = False
        self.alive = True

    @property
    def config(self) -> CameraConfig:
        return self.camera

    def start(self) -> None:
        self.started = True

    def stop(self, timeout: float | None = None) -> None:
        self.stopped = True
        self.alive = False

    def is_alive(self) -> bool:
        return self.alive

    def health(self) -> WorkerHealth:
        return WorkerHealth(self.camera.id, CameraStatus.ACTIVE, None, {})


def _camera(camera_id: int) -> CameraConfig:
    return CameraConfig(id=camera_id, name=f"cam-{camera_id}", stream_reference="rtsp://x/1")


def build_manager(*, max_concurrent: int = 1) -> tuple[CameraManager, list[FakeWorker]]:
    created: list[FakeWorker] = []

    def factory(camera: CameraConfig) -> FakeWorker:
        worker = FakeWorker(camera)
        created.append(worker)
        return worker

    manager = CameraManager(worker_factory=factory, max_concurrent=max_concurrent)
    return manager, created


def test_max_concurrent_must_be_positive() -> None:
    with pytest.raises(ValueError):
        CameraManager(worker_factory=lambda camera: FakeWorker(camera), max_concurrent=0)


def test_ensure_starts_a_worker() -> None:
    manager, created = build_manager()
    manager.ensure([_camera(1)])
    assert manager.running_ids() == [1]
    assert created[0].started is True


def test_ensure_defers_beyond_max_concurrent() -> None:
    manager, created = build_manager(max_concurrent=1)
    manager.ensure([_camera(1), _camera(2)])
    assert manager.running_ids() == [1]
    assert created[0].camera.id == 1


def test_ensure_converges_downward() -> None:
    manager, created = build_manager()
    manager.ensure([_camera(1)])
    manager.ensure([])
    assert manager.running_ids() == []
    assert created[0].stopped is True


def test_ensure_replaces_a_dead_worker() -> None:
    manager, created = build_manager()
    manager.ensure([_camera(1)])
    created[0].alive = False
    manager.ensure([_camera(1)])
    assert manager.running_ids() == [1]
    assert len(created) == 2
    assert created[1].started is True


def test_ensure_is_idempotent_for_a_live_worker() -> None:
    manager, created = build_manager()
    manager.ensure([_camera(1)])
    manager.ensure([_camera(1)])
    assert len(created) == 1


def test_ensure_restarts_a_worker_whose_config_changed() -> None:
    """An edited camera must not keep running stale rules (FR-47)."""
    manager, created = build_manager()
    original = _camera(1)
    manager.ensure([original])
    changed = CameraConfig(
        id=1,
        name="cam-1",
        stream_reference="rtsp://x/1",
        configuration={"zones": []},
    )
    manager.ensure([changed])
    assert len(created) == 2
    assert created[0].stopped is True
    assert created[1].started is True
    assert created[1].camera.configuration == {"zones": []}


def test_ensure_keeps_a_worker_whose_config_is_unchanged() -> None:
    manager, created = build_manager()
    manager.ensure([_camera(1)])
    manager.ensure([_camera(1)])  # equal by value, not identity
    assert len(created) == 1


def test_stop_single_camera() -> None:
    manager, created = build_manager(max_concurrent=2)
    manager.ensure([_camera(1), _camera(2)])
    manager.stop(1)
    assert manager.running_ids() == [2]
    assert created[0].stopped is True


def test_stop_unknown_camera_is_a_noop() -> None:
    manager, _created = build_manager()
    manager.stop(99)
    assert manager.running_ids() == []


def test_health_returns_each_worker() -> None:
    manager, _created = build_manager(max_concurrent=2)
    manager.ensure([_camera(1), _camera(2)])
    health = manager.health()
    assert {item.camera_id for item in health} == {1, 2}


def test_shutdown_stops_everything() -> None:
    manager, created = build_manager(max_concurrent=2)
    manager.ensure([_camera(1), _camera(2)])
    manager.shutdown()
    assert manager.running_ids() == []
    assert all(worker.stopped for worker in created)
