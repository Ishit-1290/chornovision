"""Supervisor control-loop tests (FR-47)."""

from __future__ import annotations

import threading

from vision.camera_manager.worker import CameraConfig
from vision.internal_client import InternalClientError, PlanCamera, RuntimePlan
from vision.supervisor import Supervisor

from .fakes import make_settings


class FakeClient:
    def __init__(self, plan: RuntimePlan | None = None, *, error: bool = False) -> None:
        self._plan = plan
        self._error = error
        self.plan_calls = 0

    def fetch_plan(self) -> RuntimePlan:
        self.plan_calls += 1
        if self._error:
            raise InternalClientError("backend down")
        assert self._plan is not None
        return self._plan


class RecordingManager:
    def __init__(self) -> None:
        self.ensure_calls: list[list[CameraConfig]] = []
        self.shutdown_called = False

    def ensure(self, cameras) -> None:
        self.ensure_calls.append(list(cameras))

    def shutdown(self) -> None:
        self.shutdown_called = True


def _camera(camera_id: int, *, enabled: bool = True) -> PlanCamera:
    return PlanCamera(
        id=camera_id,
        name=f"cam-{camera_id}",
        stream_reference="rtsp://x/1",
        enabled=enabled,
        status="stopped",
    )


def _supervisor(client: FakeClient) -> tuple[Supervisor, RecordingManager]:
    manager = RecordingManager()
    supervisor = Supervisor(client=client, settings=make_settings(), manager=manager)
    return supervisor, manager


def test_reconcile_with_stopped_monitoring_runs_nothing() -> None:
    client = FakeClient(RuntimePlan(monitoring_state="stopped", cameras=[_camera(1)]))
    supervisor, manager = _supervisor(client)

    supervisor.reconcile()

    assert manager.ensure_calls == [[]]


def test_reconcile_running_starts_enabled_cameras() -> None:
    plan = RuntimePlan(monitoring_state="running", cameras=[_camera(1), _camera(2)])
    supervisor, manager = _supervisor(FakeClient(plan))

    supervisor.reconcile()

    assert len(manager.ensure_calls) == 1
    assert [camera.id for camera in manager.ensure_calls[0]] == [1, 2]


def test_reconcile_excludes_disabled_cameras() -> None:
    plan = RuntimePlan(
        monitoring_state="running", cameras=[_camera(1, enabled=True), _camera(2, enabled=False)]
    )
    supervisor, manager = _supervisor(FakeClient(plan))

    supervisor.reconcile()

    assert [camera.id for camera in manager.ensure_calls[0]] == [1]


def test_reconcile_leaves_workers_untouched_on_client_error() -> None:
    supervisor, manager = _supervisor(FakeClient(error=True))

    supervisor.reconcile()

    assert manager.ensure_calls == []


def test_run_polls_until_stop_event() -> None:
    plan = RuntimePlan(monitoring_state="running", cameras=[_camera(1)])
    supervisor, manager = _supervisor(FakeClient(plan))
    stop = threading.Event()
    stop.set()

    supervisor.run(stop)  # returns immediately; not polling

    assert manager.ensure_calls == []

    client = FakeClient(plan)
    supervisor2, manager2 = _supervisor(client)
    stop2 = threading.Event()
    thread = threading.Thread(target=supervisor2.run, args=(stop2,))
    thread.start()
    try:
        deadline = threading.Event()
        deadline.wait(0.3)
    finally:
        stop2.set()
        thread.join(timeout=2.0)
    assert client.plan_calls >= 1
    assert manager2.ensure_calls


def test_shutdown_delegates_to_manager() -> None:
    supervisor, manager = _supervisor(FakeClient(RuntimePlan("stopped", [])))
    supervisor.shutdown()
    assert manager.shutdown_called is True


def test_reconcile_passes_camera_configuration_to_workers() -> None:
    camera = PlanCamera(
        id=1,
        name="cam-1",
        stream_reference="rtsp://x/1",
        enabled=True,
        status="stopped",
        configuration={"zones": [{"id": "room"}], "event_rules": {}},
    )
    plan = RuntimePlan(monitoring_state="running", cameras=[camera])
    supervisor, manager = _supervisor(FakeClient(plan))

    supervisor.reconcile()

    assert manager.ensure_calls[0][0].configuration == {
        "zones": [{"id": "room"}],
        "event_rules": {},
    }
