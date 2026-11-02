"""Camera-worker lifecycle, failure, and processing tests (FR-02, FR-06, FR-08, D-24).

Threaded lifecycle tests use real timers with a bounded ``wait_until`` so they exercise the
real capture/processing threads. Deterministic paths (frame handling, degradation signalling)
drive the worker's processing loop directly with fakes.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import pytest
from app.models.camera import CameraStatus

from vision.camera_manager.worker import (
    CameraConfig,
    CameraWorker,
    FrameObservation,
)
from vision.detection.detector import NullDetector
from vision.health import WorkerHealth
from vision.ingestion.sources import Frame

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

RTSP = "rtsp://192.168.1.50:554/stream1"
LOGGER = logging.getLogger("test.vision.worker")


def _frame(*, image: object, camera_id: int = 1) -> Frame:
    return Frame(
        camera_id=camera_id,
        image=image,
        position_seconds=0.0,
        arrival_monotonic=0.0,
        arrival_utc=datetime.now(UTC),
    )


def make_worker(
    reports: ReportCollector,
    *,
    settings=None,
    source_factory=None,
    detector_factory=None,
    tracker_factory=None,
    camera_id: int = 1,
    stream: str = RTSP,
    configuration: dict | None = None,
) -> CameraWorker:
    settings = settings or make_settings()
    if source_factory is None:
        source_factory = SourceFactory(
            lambda: FakeFrameSource([FakeImage()], block_when_exhausted=True)
        )
    if detector_factory is None:
        detector_factory = lambda: ScriptedDetector()  # noqa: E731
    if tracker_factory is None:
        tracker_factory = lambda: CountingTracker()  # noqa: E731
    return CameraWorker(
        CameraConfig(
            id=camera_id,
            name="front-door",
            stream_reference=stream,
            configuration=configuration,
        ),
        settings=settings,
        report=reports,
        source_factory=source_factory,
        detector_factory=detector_factory,
        tracker_factory=tracker_factory,
        logger=LOGGER,
    )


# --- lifecycle ------------------------------------------------------------------


def test_reaches_active_and_stops_cleanly() -> None:
    reports = ReportCollector()
    source = FakeFrameSource([FakeImage()], block_when_exhausted=True)
    worker = make_worker(reports, source_factory=SourceFactory(lambda: source))

    worker.start()
    assert wait_until(lambda: "active" in reports.statuses())
    worker.stop(timeout=2.0)

    assert not worker.is_alive()
    statuses = reports.statuses()
    assert statuses[0] == "connecting"
    assert "active" in statuses
    assert statuses[-1] == "stopped"
    assert "disconnected" not in statuses
    assert source.closed is True


def test_active_is_only_reported_after_a_frame_is_processed() -> None:
    reports = ReportCollector()
    worker = make_worker(reports)

    worker._capture_done = True
    worker._report(CameraStatus.CONNECTING)
    tracker = CountingTracker()
    worker._queue.put(_frame(image=FakeImage()))
    assert worker._process_loop(None, NullDetector(), tracker) is True

    assert tracker.updates == 1
    assert "active" in reports.statuses()


def test_stop_is_idempotent_and_releases_the_source() -> None:
    reports = ReportCollector()
    source = FakeFrameSource([FakeImage()], block_when_exhausted=True)
    worker = make_worker(reports, source_factory=SourceFactory(lambda: source))

    worker.start()
    assert wait_until(lambda: "active" in reports.statuses())
    worker.stop(timeout=2.0)
    worker.stop(timeout=2.0)

    assert not worker.is_alive()
    assert source.closed is True


# --- failure paths --------------------------------------------------------------


def test_insecure_target_is_terminal() -> None:
    reports = ReportCollector()
    worker = make_worker(reports, stream="rtsp://127.0.0.1:554/stream1")

    worker.start()
    assert wait_until(lambda: "failed" in reports.statuses())

    snapshot = reports.snapshot()
    assert [status for status, _, _ in snapshot] == ["connecting", "failed"]
    assert snapshot[-1][1] == "disallowed_address"
    worker.stop(timeout=2.0)


def test_detector_load_failure_is_terminal() -> None:
    reports = ReportCollector()
    source = FakeFrameSource([FakeImage()], block_when_exhausted=True)
    worker = make_worker(
        reports,
        source_factory=SourceFactory(lambda: source),
        detector_factory=lambda: ScriptedDetector(fail_load=True),
    )

    worker.start()
    assert wait_until(lambda: "failed" in reports.statuses())

    snapshot = reports.snapshot()
    assert [status for status, _, _ in snapshot] == ["connecting", "failed"]
    assert snapshot[-1][1] == "detector_load_failed"
    worker.stop(timeout=2.0)


def test_unavailable_camera_reconnects_then_fails() -> None:
    reports = ReportCollector()
    factory = SourceFactory(lambda: FakeFrameSource(open_result=False))
    settings = make_settings(reconnect_max_attempts=2)
    worker = make_worker(reports, settings=settings, source_factory=factory)

    worker.start()
    assert wait_until(lambda: "failed" in reports.statuses())

    snapshot = reports.snapshot()
    assert [status for status, _, _ in snapshot] == [
        "connecting",
        "disconnected",
        "reconnecting",
        "connecting",
        "disconnected",
        "failed",
    ]
    assert snapshot[1][1] == "open_failed"
    assert snapshot[3][1] is None
    assert snapshot[5][1] == "reconnect_exhausted"
    assert len(factory.created) == 2
    worker.stop(timeout=2.0)


def test_stalled_stream_is_reported() -> None:
    reports = ReportCollector()
    source = FakeFrameSource([FakeImage()], block_when_exhausted=True)
    settings = make_settings(read_timeout_seconds=0.05, reconnect_max_attempts=1)
    worker = make_worker(reports, settings=settings, source_factory=SourceFactory(lambda: source))

    worker.start()
    assert wait_until(lambda: "failed" in reports.statuses())

    snapshot = reports.snapshot()
    assert [status for status, _, _ in snapshot] == [
        "connecting",
        "active",
        "disconnected",
        "failed",
    ]
    assert snapshot[2][1] == "stream_stalled"
    worker.stop(timeout=2.0)


def test_every_source_is_closed_on_disconnect() -> None:
    reports = ReportCollector()
    factory = SourceFactory(lambda: FakeFrameSource([FakeImage()], block_when_exhausted=False))
    settings = make_settings(reconnect_max_attempts=1)
    worker = make_worker(reports, settings=settings, source_factory=factory)

    worker.start()
    assert wait_until(lambda: "failed" in reports.statuses())

    assert factory.created
    assert all(source.closed for source in factory.created)
    worker.stop(timeout=2.0)


# --- reconnect / tracking reset -------------------------------------------------


def test_tracker_is_reset_on_every_connection() -> None:
    reports = ReportCollector()
    tracker = CountingTracker()
    detector_calls = {"count": 0}

    def detector_factory() -> ScriptedDetector:
        detector_calls["count"] += 1
        return ScriptedDetector()

    factory = SourceFactory(lambda: FakeFrameSource([FakeImage()], block_when_exhausted=False))
    settings = make_settings(reconnect_max_attempts=2)
    worker = make_worker(
        reports,
        settings=settings,
        source_factory=factory,
        detector_factory=detector_factory,
        tracker_factory=lambda: tracker,
    )

    worker.start()
    assert wait_until(lambda: "failed" in reports.statuses())

    # FR-08: tracks are cleared on every connection (plus once on model release).
    assert tracker.resets >= 2
    assert tracker.updates == 2
    assert detector_calls["count"] == 1  # detector reused, not re-loaded per connection
    worker.stop(timeout=2.0)


# --- processing loop (deterministic) --------------------------------------------


def test_process_loop_skips_invalid_frames() -> None:
    reports = ReportCollector()
    worker = make_worker(reports)
    worker._capture_done = True
    worker._queue.put(_frame(image=object()))  # no ``shape`` → invalid

    tracker = CountingTracker()
    assert worker._process_loop(None, NullDetector(), tracker) is False

    assert worker.health().metrics["frames_invalid"] == 1
    assert tracker.updates == 0


def test_process_loop_buffers_processed_frames() -> None:
    reports = ReportCollector()
    worker = make_worker(reports, camera_id=7)
    worker._capture_done = True
    worker._queue.put(_frame(image=FakeImage(), camera_id=7))

    assert worker._process_loop(None, NullDetector(), CountingTracker()) is True

    buffered = worker._buffer.snapshot()
    assert len(buffered) == 1
    assert isinstance(buffered[0], FrameObservation)
    assert buffered[0].camera_id == 7


def test_rotation_feeds_upright_frames_to_the_detector_and_maps_boxes_back() -> None:
    """D-72: the detector sees a rotated frame; tracking sees the original frame."""
    np = pytest.importorskip("numpy")
    from vision.detection.detector import Detection

    class RecordingDetector:
        name = "recording"

        def __init__(self) -> None:
            self.shapes: list[tuple[int, ...]] = []

        def load(self) -> None:  # pragma: no cover - not used by _process_loop
            pass

        def detect(self, image: object) -> list[Detection]:
            self.shapes.append(image.shape)  # type: ignore[attr-defined]
            return [
                Detection(
                    class_id=0,
                    class_name="person",
                    confidence=0.9,
                    bbox=(10.0, 20.0, 40.0, 60.0),
                )
            ]

        def close(self) -> None:  # pragma: no cover - not used by _process_loop
            pass

    class RecordingTracker:
        name = "recording"

        def __init__(self) -> None:
            self.detections: list[Detection] = []

        def reset(self) -> None:  # pragma: no cover - not used by _process_loop
            pass

        def update(self, detections: list[Detection]) -> list:
            self.detections = list(detections)
            return []

    source = np.zeros((48, 64, 3), dtype=np.uint8)  # height=48, width=64
    reporter = ReportCollector()
    detector = RecordingDetector()
    tracker = RecordingTracker()
    worker = make_worker(reporter, configuration={"rotation": 90})
    worker._capture_done = True
    worker._queue.put(_frame(image=source))

    assert worker._process_loop(None, detector, tracker) is True

    # Detection ran on the upright (rotated) frame: 64x48 -> 48x64 (w x h).
    assert detector.shapes == [(64, 48, 3)]
    # The box is mapped back into the original frame before tracking.
    assert len(tracker.detections) == 1
    assert tracker.detections[0].bbox == (20.0, 8.0, 60.0, 38.0)


def test_degraded_is_reported_when_frames_are_dropped() -> None:
    reports = ReportCollector()
    settings = make_settings(degraded_window_frames=1, degraded_drop_ratio=0.5, queue_maxsize=1)
    worker = make_worker(reports, settings=settings)

    for _ in range(4):
        worker._metrics.record_received()
    worker._metrics.record_processing(0.0, 0.001)
    for _ in range(5):  # maxsize=1 → 4 drops
        worker._queue.put("frame")
    assert worker._queue.dropped == 4

    worker._evaluate_degraded()

    assert reports.statuses()[-1] == "degraded"


def test_active_is_reported_when_there_is_no_backpressure() -> None:
    reports = ReportCollector()
    settings = make_settings(degraded_window_frames=1, degraded_drop_ratio=0.5, queue_maxsize=8)
    worker = make_worker(reports, settings=settings)

    for _ in range(3):
        worker._metrics.record_received()
    worker._metrics.record_processing(0.0, 0.001)
    for _ in range(3):
        worker._queue.put("frame")

    worker._evaluate_degraded()

    assert reports.statuses()[-1] == "active"


# --- health snapshot ------------------------------------------------------------


def test_health_snapshot_is_non_sensitive_and_complete() -> None:
    reports = ReportCollector()
    worker = make_worker(reports, camera_id=3)

    health = worker.health()

    assert isinstance(health, WorkerHealth)
    assert health.camera_id == 3
    for key in (
        "queue_depth",
        "queue_max_depth",
        "frames_dropped",
        "frames_processed",
        "ingest_fps",
        "process_fps",
    ):
        assert key in health.metrics
    assert RTSP not in str(health.metrics)
