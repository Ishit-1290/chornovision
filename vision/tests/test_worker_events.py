"""Camera-worker ↔ event-engine wiring tests (Phase 5)."""

from __future__ import annotations

from vision.camera_manager.worker import CameraConfig, CameraWorker
from vision.detection.detector import NullDetector
from vision.ingestion.sources import RawFrame
from vision.tracking.tracker import Track

from .event_helpers import FULL_POLYGON, START, CollectingSink
from .fakes import (
    CountingTracker,
    FakeFrameSource,
    FakeImage,
    ReportCollector,
    SourceFactory,
    make_settings,
)

OUTSIDE = (45.0, 20.0, 55.0, 40.0)
INSIDE = (45.0, 40.0, 55.0, 60.0)


def _entrance_configuration() -> dict:
    return {
        "zones": [
            {
                "id": "entrance",
                "name": "Main Entrance",
                "kind": "entrance",
                "polygon": FULL_POLYGON,
                "boundary": {
                    "p1": {"x": 0.0, "y": 0.5},
                    "p2": {"x": 1.0, "y": 0.5},
                    "inside_side": "left",
                },
            }
        ],
        "event_rules": {
            "entrance_zone_id": "entrance",
            "thresholds": {
                "boundary_confirm_frames": 1,
                "boundary_cooldown_seconds": 0.0,
            },
        },
    }


def _crowd_configuration() -> dict:
    return {
        "zones": [{"id": "room", "name": "Room", "kind": "room", "polygon": FULL_POLYGON}],
        "event_rules": {
            "room_zone_id": "room",
            "thresholds": {
                "occupancy_persistence_seconds": 1000.0,
                "crowd_occupancy_threshold": 1,
                "crowd_persistence_seconds": 0.0,
            },
        },
    }


def _worker(
    configuration: dict | None,
    sink: CollectingSink,
    *,
    reports: ReportCollector | None = None,
) -> CameraWorker:
    return CameraWorker(
        CameraConfig(
            id=1,
            name="front-door",
            stream_reference="rtsp://192.168.1.50:554/stream1",
            configuration=configuration,
        ),
        settings=make_settings(),
        report=reports or ReportCollector(),
        source_factory=SourceFactory(lambda: FakeFrameSource([FakeImage()])),
        detector_factory=NullDetector,
        tracker_factory=CountingTracker,
        wall_clock=lambda: START,
        event_sink=sink,
    )


def _track(bbox: tuple[float, float, float, float]) -> Track:
    return Track(track_id=1, class_name="person", confidence=0.9, bbox=bbox)


def test_worker_publishes_events_for_processed_frames() -> None:
    sink = CollectingSink()
    worker = _worker(_entrance_configuration(), sink)

    worker._observe_events(FakeImage(100, 100), [_track(OUTSIDE)], 0.0)
    worker._observe_events(FakeImage(100, 100), [_track(INSIDE)], 1.0)

    assert sink.event_types == ["person_entering", "person_entering"]
    assert worker.health().metrics["events_emitted"] == 2
    assert worker.health().metrics["event_errors"] == 0


def test_worker_finalises_open_events_when_the_stream_ends() -> None:
    sink = CollectingSink()
    worker = _worker(_crowd_configuration(), sink)

    worker._observe_events(FakeImage(100, 100), [_track(INSIDE)], 0.0)
    worker._observe_events(FakeImage(100, 100), [_track(INSIDE)], 1.0)
    worker._finalise_events()

    assert sink.statuses[0] == "active"
    assert sink.statuses[-1] == "uncertain"
    assert sink.transitions[-1].event.attributes["completion_reason"] == "stream_ended"


def test_worker_with_invalid_configuration_still_runs_without_rules() -> None:
    sink = CollectingSink()
    worker = _worker(
        {"event_rules": {"room_zone_id": "missing-zone"}},
        sink,
    )

    assert worker._engine is None
    worker._observe_events(FakeImage(), [_track(INSIDE)], 0.0)
    assert sink.transitions == []


def test_worker_without_configuration_still_enables_motionlessness() -> None:
    worker = _worker(None, CollectingSink())

    assert worker._engine is not None
    assert [event.value for event in worker._engine.event_types] == ["person_motionless"]


class _RecordingEngine:
    def __init__(self) -> None:
        self.resets = 0
        self.observed = 0
        self.finalised = False

    def reset(self) -> None:
        self.resets += 1

    def observe(self, frame) -> list:
        self.observed += 1
        return []

    def on_stream_end(self, **_kwargs) -> list:
        self.finalised = True
        return []


def test_run_session_resets_and_finalises_the_event_engine() -> None:
    worker = _worker(None, CollectingSink())
    engine = _RecordingEngine()
    worker._engine = engine  # type: ignore[assignment]

    source = FakeFrameSource([], block_when_exhausted=False)
    seed = RawFrame(image=FakeImage(), position_seconds=0.0)
    worker._run_session(source, seed)

    assert engine.resets == 1
    assert engine.observed == 1
    assert engine.finalised is True
