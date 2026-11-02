"""Frame-acquisition boundary tests (FR-07)."""

from __future__ import annotations

from datetime import UTC, datetime

from vision.ingestion.sources import Frame, RawFrame, tag_frame

from .fakes import FakeImage, write_test_video


def test_tag_frame_attaches_ingestion_metadata() -> None:
    raw = RawFrame(image=FakeImage(), position_seconds=1.5)
    frame = tag_frame(7, raw, clock=lambda: 42.0)

    assert isinstance(frame, Frame)
    assert frame.camera_id == 7
    assert frame.image is raw.image
    assert frame.position_seconds == 1.5
    assert frame.arrival_monotonic == 42.0
    assert isinstance(frame.arrival_utc, datetime)
    assert frame.arrival_utc.tzinfo is UTC


def test_opencv_source_reads_frames_from_a_clip(tmp_path) -> None:
    import pytest

    pytest.importorskip("cv2")
    path = write_test_video(tmp_path / "clip.avi", frames=6)
    from vision.ingestion.sources import OpenCVFrameSource

    source = OpenCVFrameSource(str(path), open_timeout=1.0, read_timeout=1.0)
    try:
        assert source.open() is True
        first = source.read()
        assert first is not None
        assert first.image is not None
        assert source.last_frame_monotonic is not None
    finally:
        source.close()
    # ``close`` is idempotent and safe to call repeatedly.
    source.close()
    assert source.read() is None


def test_opencv_source_open_fails_for_missing_file() -> None:
    import pytest

    pytest.importorskip("cv2")
    from vision.ingestion.sources import OpenCVFrameSource

    source = OpenCVFrameSource("/nonexistent/definitely-missing-clip.avi")
    try:
        assert source.open() is False
    finally:
        source.close()
