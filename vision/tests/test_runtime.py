"""Vision runtime wiring tests (FR-02, W §14)."""

from __future__ import annotations

import logging

from app.models.camera import CameraStatus

from vision import runtime
from vision.camera_manager.worker import CameraConfig, CameraWorker
from vision.config import TrackerKind
from vision.internal_client import StateReport
from vision.supervisor import Supervisor
from vision.tracking.tracker import ByteTrackTracker, IoUTracker

from .fakes import make_settings

LOGGER = logging.getLogger("test.vision.runtime")
RTSP = "rtsp://192.168.1.50:554/stream1"


class FakeClient:
    def __init__(self) -> None:
        self.reports: list[tuple[int, str, str | None]] = []
        self.reconcile_count = 0

    def report_state(self, camera_id, status, *, detail=None, metrics=None):
        self.reports.append((camera_id, status, detail))
        return StateReport(camera_id=camera_id, status=status, applied=True)

    def reconcile(self) -> int:
        self.reconcile_count += 1
        return 2

    def fetch_plan(self):  # pragma: no cover - not exercised here
        raise AssertionError("fetch_plan should not be called")


def test_tracker_factory_selects_configured_tracker() -> None:
    assert isinstance(runtime._tracker_for(make_settings(tracker=TrackerKind.IOU)), IoUTracker)
    assert isinstance(
        runtime._tracker_for(make_settings(tracker=TrackerKind.BYTETRACK)), ByteTrackTracker
    )


def test_build_supervisor_wires_a_manager() -> None:
    settings = make_settings(max_concurrent_cameras=1)
    supervisor = runtime.build_supervisor(settings, client=FakeClient())

    assert isinstance(supervisor, Supervisor)
    assert supervisor.manager.running_ids() == []


def test_build_worker_reports_state_through_the_client() -> None:
    settings = make_settings()
    client = FakeClient()
    worker = runtime._build_worker(
        CameraConfig(id=5, name="front", stream_reference=RTSP),
        settings=settings,
        client=client,
        logger=LOGGER,
    )

    assert isinstance(worker, CameraWorker)
    worker._report(CameraStatus.CONNECTING)

    assert client.reports == [(5, "connecting", None)]


class FakeCoordinator:
    def __init__(self) -> None:
        self.bound = None
        self.shutdowns = 0

    def bind_buffer(self, buffer) -> None:
        self.bound = buffer

    def on_frame(self, frame, monotonic=None) -> None:
        return None

    def on_stream_end(self, monotonic=None) -> None:
        return None

    def reset(self) -> None:
        return None

    def shutdown(self, timeout: float = 5.0) -> None:
        self.shutdowns += 1

    def counters(self) -> dict[str, int]:
        return {"evidence_active_captures": 0}


def test_build_worker_wires_the_evidence_coordinator() -> None:
    coordinator = FakeCoordinator()
    worker = runtime._build_worker(
        CameraConfig(id=6, name="front", stream_reference=RTSP),
        settings=make_settings(),
        client=FakeClient(),
        coordinator=coordinator,  # type: ignore[arg-type]
        logger=LOGGER,
    )

    assert coordinator.bound is worker._buffer  # noqa: SLF001 - wiring assertion
    worker.stop()
    assert coordinator.shutdowns == 1


def test_build_coordinator_uses_bounded_settings() -> None:
    settings = make_settings(
        evidence_handoff_queue_maxsize=7,
        evidence_handoff_spool_max_mb=2,
        evidence_handoff_max_attempts=4,
        evidence_encoder_queue_maxsize=3,
    )

    coordinator = runtime._build_coordinator(
        CameraConfig(id=2, name="front", stream_reference=RTSP),
        settings=settings,
        client=FakeClient(),  # type: ignore[arg-type]
        logger=LOGGER,
    )

    assert coordinator.camera_id == 2
    assert coordinator._handoff.queue_maxsize == 7  # noqa: SLF001
    assert coordinator._handoff.spool_max_bytes == 2 * 1024 * 1024  # noqa: SLF001
    assert coordinator._handoff.max_attempts == 4  # noqa: SLF001
    assert coordinator._manager._jobs.maxsize == 3  # noqa: SLF001


def test_build_coordinator_forwards_camera_rotation() -> None:
    """D-72/D-73: evidence is written in the camera rotation the live view uses."""
    coordinator = runtime._build_coordinator(
        CameraConfig(
            id=3,
            name="sideways",
            stream_reference=RTSP,
            configuration={"rotation": 90},
        ),
        settings=make_settings(),
        client=FakeClient(),  # type: ignore[arg-type]
        logger=LOGGER,
    )
    default = runtime._build_coordinator(
        CameraConfig(id=4, name="upright", stream_reference=RTSP),
        settings=make_settings(),
        client=FakeClient(),  # type: ignore[arg-type]
        logger=LOGGER,
    )

    assert coordinator._manager._rotation == 90  # noqa: SLF001
    assert default._manager._rotation == 0  # noqa: SLF001


def test_main_reconciles_then_runs_and_shuts_down(monkeypatch) -> None:
    settings = make_settings()
    client = FakeClient()

    class FakeSupervisor:
        def __init__(self) -> None:
            self.ran = False
            self.shutdown_called = False

        def run(self, stop_event) -> None:
            self.ran = True
            stop_event.set()

        def shutdown(self) -> None:
            self.shutdown_called = True

    supervisor = FakeSupervisor()

    monkeypatch.setattr(runtime, "get_vision_settings", lambda: settings)
    monkeypatch.setattr(runtime, "InternalClient", lambda **kwargs: client)
    monkeypatch.setattr(runtime, "build_supervisor", lambda settings, client=None: supervisor)
    monkeypatch.setattr(runtime, "_install_signal_handlers", lambda stop_event: None)

    exit_code = runtime.main([])

    assert exit_code == 0
    assert client.reconcile_count == 1
    assert supervisor.ran is True
    assert supervisor.shutdown_called is True
