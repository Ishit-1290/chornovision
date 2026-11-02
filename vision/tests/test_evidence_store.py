"""Filesystem evidence store tests (Phase 6; FR-36, FR-39)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from vision.evidence.store import EvidenceStore

CAPTURED = datetime(2026, 3, 7, 4, 5, 6, tzinfo=UTC)


class FakeEncoder:
    """Writes a scripted payload (or fails) without OpenCV."""

    def __init__(self, *, payload: bytes = b"payload", fail: bool = False) -> None:
        self.payload = payload
        self.fail = fail
        self.snapshot_path: Path | None = None
        self.clip_path: Path | None = None
        self.clip_fps: float | None = None
        self.clip_frames = 0

    def write_snapshot(self, path: Path, image) -> None:  # noqa: ARG002
        if self.fail:
            raise RuntimeError("encoder boom")
        self.snapshot_path = path
        path.write_bytes(self.payload)

    def write_clip(self, path: Path, frames, fps: float) -> None:
        if self.fail:
            raise RuntimeError("encoder boom")
        self.clip_path = path
        self.clip_fps = fps
        self.clip_frames = len(frames)
        path.write_bytes(self.payload)


def _store(tmp_path: Path, encoder: FakeEncoder) -> EvidenceStore:
    return EvidenceStore(root=tmp_path, encoder=encoder)


def test_snapshot_is_written_under_the_evidence_root(tmp_path: Path) -> None:
    encoder = FakeEncoder()
    record = _store(tmp_path, encoder).save_snapshot(
        camera_id=2, event_id="evt", captured_at=CAPTURED, image=object()
    )

    assert record.status == "available"
    assert record.media_type == "snapshot"
    assert record.relative_path == "camera-2/2026/03/07/evt-snapshot.jpg"
    assert record.file_size_bytes == len(b"payload")
    path = tmp_path / record.relative_path
    assert path.is_file()
    assert encoder.snapshot_path == path


def test_clip_duration_is_derived_from_frame_count_and_fps(tmp_path: Path) -> None:
    encoder = FakeEncoder()
    record = _store(tmp_path, encoder).save_clip(
        camera_id=1,
        event_id="evt",
        captured_at=CAPTURED,
        frames=[object(), object(), object()],
        fps=5.0,
    )

    assert record.status == "available"
    assert record.duration_seconds == 0.6
    assert encoder.clip_frames == 3
    assert record.relative_path == "camera-1/2026/03/07/evt-clip.mp4"


def test_empty_clip_is_an_explicit_failure(tmp_path: Path) -> None:
    record = _store(tmp_path, FakeEncoder()).save_clip(
        camera_id=1, event_id="evt", captured_at=CAPTURED, frames=[], fps=5.0
    )

    assert record.status == "failed"
    assert record.error == "no_frames"
    assert record.relative_path is None


def test_encoder_error_is_reported_and_partial_file_removed(tmp_path: Path) -> None:
    encoder = FakeEncoder(fail=True)
    record = _store(tmp_path, encoder).save_snapshot(
        camera_id=1, event_id="evt", captured_at=CAPTURED, image=object()
    )

    assert record.status == "failed"
    assert record.error == "encode_failed"
    assert not (tmp_path / "camera-1/2026/03/07/evt-snapshot.jpg").exists()


def test_zero_byte_file_is_a_failure_and_removed(tmp_path: Path) -> None:
    encoder = FakeEncoder(payload=b"")
    record = _store(tmp_path, encoder).save_snapshot(
        camera_id=1, event_id="evt", captured_at=CAPTURED, image=object()
    )

    assert record.status == "failed"
    assert record.error == "empty_file"
    assert not (tmp_path / "camera-1/2026/03/07/evt-snapshot.jpg").exists()


def test_unsafe_event_id_cannot_escape_the_root(tmp_path: Path) -> None:
    encoder = FakeEncoder()
    record = _store(tmp_path, encoder).save_snapshot(
        camera_id=1, event_id="../../etc/passwd", captured_at=CAPTURED, image=object()
    )

    assert record.status == "available"
    assert record.relative_path is not None
    assert (tmp_path / record.relative_path).is_file()
    assert (tmp_path / record.relative_path).resolve().is_relative_to(tmp_path.resolve())
