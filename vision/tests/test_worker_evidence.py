"""Camera-worker ↔ evidence-coordinator wiring tests (Phase 6)."""

from __future__ import annotations

from vision.camera_manager.worker import CameraConfig, CameraWorker
from vision.detection.detector import NullDetector
from vision.ingestion.sources import RawFrame

from .fakes import (
    CountingTracker,
    FakeFrameSource,
    FakeImage,
    ReportCollector,
    SourceFactory,
    make_settings,
)


class FakeEvidence:
    def __init__(self) -> None:
        self.bound = None
        self.frames: list[tuple[object, float | None]] = []
        self.ends: list[float | None] = []
        self.resets = 0
        self.shutdowns = 0

    def bind_buffer(self, buffer) -> None:
        self.bound = buffer

    def on_frame(self, frame, monotonic=None) -> None:
        self.frames.append((frame, monotonic))

    def on_stream_end(self, monotonic=None) -> None:
        self.ends.append(monotonic)

    def reset(self) -> None:
        self.resets += 1

    def shutdown(self, timeout: float = 5.0) -> None:  # noqa: ARG002
        self.shutdowns += 1

    def counters(self) -> dict[str, int]:
        return {
            "evidence_active_captures": 0,
            "evidence_capture_started": 0,
            "evidence_registered": 0,
            "handoff_delivered": 0,
        }


def _worker(
    evidence: FakeEvidence | None = None,
    *,
    configuration: dict | None = None,
    reports: ReportCollector | None = None,
) -> CameraWorker:
    return CameraWorker(
        CameraConfig(
            id=1,
            name="front",
            stream_reference="rtsp://192.168.1.50:554/stream1",
            configuration=configuration,
        ),
        settings=make_settings(),
        report=reports or ReportCollector(),
        source_factory=SourceFactory(
            lambda: FakeFrameSource([FakeImage()], block_when_exhausted=False)
        ),
        detector_factory=NullDetector,
        tracker_factory=CountingTracker,
        evidence=evidence,
    )


def test_constructor_binds_the_rolling_buffer() -> None:
    evidence = FakeEvidence()
    worker = _worker(evidence)

    assert evidence.bound is worker._buffer  # noqa: SLF001 - wiring assertion


def test_processed_frames_are_forwarded_to_evidence() -> None:
    evidence = FakeEvidence()
    worker = _worker(evidence)
    source = FakeFrameSource([FakeImage()], block_when_exhausted=False)
    seed = RawFrame(image=FakeImage(), position_seconds=0.0)

    worker._run_session(source, seed)  # noqa: SLF001 - focused integration

    assert evidence.frames, "the processed frame should reach the evidence manager"
    frame, monotonic = evidence.frames[0]
    assert hasattr(frame, "monotonic")
    assert isinstance(monotonic, float)
    assert evidence.resets == 1
    assert evidence.ends, "stream end must finalise open captures"


def test_stream_end_finalises_evidence_without_an_event_engine() -> None:
    evidence = FakeEvidence()
    worker = _worker(
        evidence,
        configuration={"event_rules": {"room_zone_id": "missing-zone"}},
    )

    assert worker._engine is None  # noqa: SLF001 - invalid rules disable the engine
    worker._finalise_events()  # noqa: SLF001

    assert len(evidence.ends) == 1
    assert isinstance(evidence.ends[0], float)


def test_health_metrics_include_evidence_counters() -> None:
    evidence = FakeEvidence()
    worker = _worker(evidence)

    metrics = worker.health().metrics

    assert metrics["evidence_active_captures"] == 0
    assert metrics["handoff_delivered"] == 0


def test_stop_shuts_the_coordinator_down() -> None:
    evidence = FakeEvidence()
    worker = _worker(evidence)

    worker.stop()

    assert evidence.shutdowns == 1


def test_worker_without_evidence_still_processes_frames() -> None:
    reports = ReportCollector()
    worker = _worker(None, reports=reports)
    source = FakeFrameSource([FakeImage()], block_when_exhausted=False)

    processed = worker._run_session(source, RawFrame(image=FakeImage()))  # noqa: SLF001

    assert processed is True
    assert "evidence_active_captures" not in worker.health().metrics
