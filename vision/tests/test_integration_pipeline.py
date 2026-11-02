"""End-to-end pipeline tests over a locally generated synthetic clip (Phase 4).

These run the real OpenCV decoder and the real (dependency-free) detector/tracker boundary
against a tiny clip written on the fly, so the ingestion → processing → health path is
exercised without any network source. They skip cleanly where OpenCV is unavailable. The
optional ``weights`` test loads real YOLO weights only when explicitly opted in, so no
model download happens in a normal test run.
"""

from __future__ import annotations

import logging
import os

import pytest

from vision.camera_manager.worker import CameraConfig, CameraWorker
from vision.detection.detector import NullDetector, YoloDetector
from vision.ingestion.prepare import is_valid_frame
from vision.ingestion.sources import OpenCVFrameSource
from vision.tracking.tracker import IoUTracker

from .fakes import ReportCollector, SourceFactory, make_settings, wait_until, write_test_video

LOGGER = logging.getLogger("test.vision.integration")
RTSP = "rtsp://192.168.1.50:554/stream1"


def test_frames_are_processed_from_a_synthetic_clip(tmp_path) -> None:
    pytest.importorskip("cv2")
    path = write_test_video(tmp_path / "clip.avi", frames=10)

    reports = ReportCollector()
    factory = SourceFactory(
        lambda: OpenCVFrameSource(str(path), open_timeout=1.0, read_timeout=0.5)
    )
    settings = make_settings(
        read_timeout_seconds=0.5,
        reconnect_max_attempts=1,
        process_target_fps=1000.0,
    )
    worker = CameraWorker(
        CameraConfig(id=1, name="clip", stream_reference=RTSP),
        settings=settings,
        report=reports,
        source_factory=factory,
        detector_factory=lambda: NullDetector(),
        tracker_factory=lambda: IoUTracker(),
        logger=LOGGER,
    )

    worker.start()
    try:
        assert wait_until(lambda: "active" in reports.statuses(), timeout=10.0)
        assert reports.report_metrics("active").get("frames_processed", 0) >= 1
    finally:
        worker.stop(timeout=5.0)

    assert not worker.is_alive()
    # The decoder was released when the session ended.
    assert factory.created and factory.created[0]._cap is None


def test_decoded_frame_is_valid(tmp_path) -> None:
    pytest.importorskip("cv2")
    path = write_test_video(tmp_path / "clip.avi", frames=4)
    source = OpenCVFrameSource(str(path), open_timeout=1.0, read_timeout=0.5)
    try:
        assert source.open() is True
        raw = source.read()
        assert raw is not None
        assert is_valid_frame(raw.image) is True
    finally:
        source.close()


@pytest.mark.weights
def test_real_yolo_loads_and_runs(monkeypatch) -> None:
    """Opt-in only: loads real weights (may download) and runs one inference."""
    if os.environ.get("VISION_TEST_WEIGHTS") != "1":
        pytest.skip("set VISION_TEST_WEIGHTS=1 to run the real-weights test")
    pytest.importorskip("ultralytics")
    np = pytest.importorskip("numpy")

    weights = os.environ.get("VISION_TEST_WEIGHTS_FILE", "yolo11n.pt")
    detector = YoloDetector(weights=weights, device="cpu")
    try:
        detector.load()
        detections = detector.detect(np.zeros((640, 640, 3), dtype=np.uint8))
        assert isinstance(detections, list)
    finally:
        detector.close()
