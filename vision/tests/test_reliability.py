"""Camera-worker lifecycle reliability tests (Phase 8; FR-04, FR-06, FR-08, NFR-03).

These cover the failure/recovery behaviour that keeps a multi-camera runtime trustworthy:
prompt, bounded shutdown even while a camera is connecting or backing off; no restart churn
after a terminal failure; tracker/engine reset on every (re)connection; safe repeated
start/stop; and a manager that replaces a dead worker and applies configuration changes.

Threaded paths use bounded ``wait_until`` synchronisation rather than fixed sleeps so the
tests do not depend on machine speed.
"""

from __future__ import annotations

import logging
import threading
import time

from vision.camera_manager.manager import CameraManager
from vision.camera_manager.worker import CameraConfig, CameraWorker

from .fakes import (
    CountingTracker,
    FakeFrameSource,
    FakeImage,
    ReportCollector,
    ScriptedDetector,
    SourceFactory,
    make_settings,
    wait_until,
)
from .test_multi_camera import KeyedReports, _build, _config

LOGGER = logging.getLogger("test.vision.reliability")
RTSP = "rtsp://192.168.1.50:554/stream1"
INSECURE = "rtsp://127.0.0.1:554/stream1"


class GatedOpenSource(FakeFrameSource):
    """A source whose ``open`` blocks until the worker is stopped (a connecting camera)."""

    def __init__(self) -> None:
        super().__init__([], block_when_exhausted=True)
        self.open_called = threading.Event()

    def open(self) -> bool:
        self.open_called.set()
        self._closed.wait(5.0)
        return False


class RecordingEngine:
    """Records reset/observe/finalise calls (stands in for the temporal engine)."""

    def __init__(self) -> None:
        self.resets = 0
        self.observed = 0
        self.finalised = False

    def reset(self) -> None:
        self.resets += 1

    def observe(self, frame: object) -> list:
        self.observed += 1
        return []

    def on_stream_end(self, **_kwargs: object) -> list:
        self.finalised = True
        return []


def make_worker(
    reports: ReportCollector,
    *,
    settings=None,
    source_factory=None,
    detector_factory=None,
    tracker_factory=None,
    stream: str = RTSP,
) -> CameraWorker:
    settings = settings or make_settings()
    if source_factory is None:
        source_factory = SourceFactory(
            lambda: FakeFrameSource([FakeImage()], block_when_exhausted=True)
        )
    return CameraWorker(
        CameraConfig(id=1, name="front-door", stream_reference=stream),
        settings=settings,
        report=reports,
        source_factory=source_factory,
        detector_factory=detector_factory or (lambda: ScriptedDetector()),
        tracker_factory=tracker_factory or CountingTracker,
        logger=LOGGER,
    )


# --- bounded, prompt shutdown ---------------------------------------------------


def test_duplicate_start_and_repeated_stop_are_safe() -> None:
    reports = ReportCollector()
    source = FakeFrameSource([FakeImage()], block_when_exhausted=True)
    worker = make_worker(reports, source_factory=SourceFactory(lambda: source))

    worker.start()
    worker.start()  # second start while alive is a no-op
    assert wait_until(lambda: "active" in reports.statuses())

    worker.stop(timeout=2.0)
    worker.stop(timeout=2.0)
    assert not worker.is_alive()
    assert source.closed is True


def test_stop_while_connecting_returns_promptly() -> None:
    reports = ReportCollector()
    source = GatedOpenSource()
    worker = make_worker(reports, source_factory=SourceFactory(lambda: source))

    worker.start()
    assert wait_until(source.open_called.is_set, timeout=3.0)
    # The worker is parked inside ``open``. A stop must not wait for the connect timeout.
    started = time.monotonic()
    worker.stop(timeout=2.0)
    elapsed = time.monotonic() - started

    assert not worker.is_alive()
    assert elapsed < 1.0
    assert reports.statuses()[-1] == "stopped"


def test_stop_during_reconnect_backoff_is_prompt() -> None:
    reports = ReportCollector()
    settings = make_settings(
        reconnect_initial_backoff_seconds=5.0,
        reconnect_max_backoff_seconds=5.0,
        reconnect_max_attempts=0,
    )
    factory = SourceFactory(lambda: FakeFrameSource(open_result=False))
    worker = make_worker(reports, settings=settings, source_factory=factory)

    worker.start()
    assert wait_until(lambda: "reconnecting" in reports.statuses(), timeout=3.0)

    started = time.monotonic()
    worker.stop(timeout=2.0)
    elapsed = time.monotonic() - started

    assert not worker.is_alive()
    assert elapsed < 1.0
    assert reports.statuses()[-1] == "stopped"


# --- terminal failure policy ----------------------------------------------------


def test_terminal_failure_idles_without_restart_churn() -> None:
    reports = ReportCollector()
    worker = make_worker(reports, stream=INSECURE)

    worker.start()
    assert wait_until(lambda: "failed" in reports.statuses(), timeout=3.0)

    # Exactly one connecting + failed report: no restart loop, and the thread idles.
    assert [status for status, _, _ in reports.snapshot()] == ["connecting", "failed"]
    assert worker.is_alive() is True
    worker.stop(timeout=2.0)


def test_rapid_start_stop_cycles_are_stable() -> None:
    for _ in range(5):
        reports = ReportCollector()
        source = FakeFrameSource([FakeImage()], block_when_exhausted=True)
        worker = make_worker(reports, source_factory=SourceFactory(lambda source=source: source))

        worker.start()
        assert wait_until(lambda reports=reports: "active" in reports.statuses(), timeout=3.0)
        worker.stop(timeout=2.0)
        assert not worker.is_alive()
        assert source.closed is True


def test_tracker_and_engine_reset_on_every_connection() -> None:
    reports = ReportCollector()
    tracker = CountingTracker()
    settings = make_settings(reconnect_max_attempts=2)
    factory = SourceFactory(lambda: FakeFrameSource([FakeImage()], block_when_exhausted=False))
    worker = make_worker(
        reports, settings=settings, source_factory=factory, tracker_factory=lambda: tracker
    )
    engine = RecordingEngine()
    worker._engine = engine  # type: ignore[assignment]

    worker.start()
    assert wait_until(lambda: "failed" in reports.statuses(), timeout=3.0)

    # FR-08: two sessions were run, each resetting tracking and the event engine.
    assert engine.resets == 2
    assert tracker.resets >= 2
    worker.stop(timeout=2.0)


# --- manager reconciliation -----------------------------------------------------


def test_manager_replaces_a_dead_worker() -> None:
    reports = KeyedReports()
    created: list[CameraWorker] = []

    def factory(camera: CameraConfig) -> CameraWorker:
        worker = _build(camera, reports=reports)
        created.append(worker)
        return worker

    manager = CameraManager(worker_factory=factory, max_concurrent=1, stop_timeout=2.0)
    manager.ensure([_config(1)])
    try:
        assert len(created) == 1
        # Kill the worker out from under the manager (simulating a dead thread).
        created[0].stop(timeout=2.0)
        assert not created[0].is_alive()

        manager.ensure([_config(1)])
        assert len(created) == 2
        assert created[1].is_alive() is True
    finally:
        manager.shutdown()


def test_manager_applies_a_config_change_to_a_running_camera() -> None:
    reports = KeyedReports()
    created: list[CameraWorker] = []

    def factory(camera: CameraConfig) -> CameraWorker:
        worker = _build(camera, reports=reports)
        created.append(worker)
        return worker

    manager = CameraManager(worker_factory=factory, max_concurrent=1, stop_timeout=2.0)
    manager.ensure([_config(1, configuration={"zones": []})])
    try:
        assert wait_until(lambda: "active" in reports.statuses(1), timeout=3.0)
        # The camera's zones were edited: the manager must restart it with the new rules.
        manager.ensure([_config(1, configuration={"zones": [{"id": "room"}]})])
        assert len(created) == 2
        assert created[0].is_alive() is False
        assert created[1].config.configuration == {"zones": [{"id": "room"}]}
    finally:
        manager.shutdown()


def test_concurrent_ensure_calls_converge_safely() -> None:
    reports = KeyedReports()
    manager = CameraManager(
        worker_factory=lambda camera: _build(camera, reports=reports),
        max_concurrent=4,
        stop_timeout=2.0,
    )
    cameras = [_config(camera_id) for camera_id in (1, 2, 3)]
    errors: list[BaseException] = []

    def converge() -> None:
        try:
            manager.ensure(cameras)
        except BaseException as exc:  # noqa: BLE001 - surfaced in the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=converge) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5.0)
    try:
        assert errors == []
        assert manager.running_ids() == [1, 2, 3]
    finally:
        manager.shutdown()
