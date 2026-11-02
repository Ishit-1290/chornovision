"""Multiple-camera isolation and attribution tests (Phase 8; FR-06, AC-04, NFR-01).

Phase 8 runs one independent worker per camera inside a single vision process: each camera
has its own lifecycle, capture thread, processing loop, bounded queue, tracker, event engine,
and event/evidence handoff. These tests prove the *isolation* contract that model is chosen
for:

* a terminal failure on one camera never stops or degrades another camera;
* a camera that blocks (stuck detector) never blocks another camera's processing;
* every event stays attributed to the camera that produced it, even under interleaved input.

They use the real :class:`~vision.camera_manager.worker.CameraWorker` and
:class:`~vision.camera_manager.manager.CameraManager` with dependency-free fakes, so the
threading is real but no network or model weights are required.
"""

from __future__ import annotations

import logging
import threading

from app.models.camera import CameraStatus

from vision.camera_manager.manager import CameraManager
from vision.camera_manager.worker import CameraConfig, CameraWorker
from vision.detection.detector import Detection, NullDetector
from vision.tracking.tracker import Track

from .event_helpers import FULL_POLYGON, CollectingSink
from .fakes import (
    CountingTracker,
    FakeFrameSource,
    FakeImage,
    ScriptedDetector,
    SourceFactory,
    make_settings,
    wait_until,
)

LOGGER = logging.getLogger("test.vision.multi_camera")
HEALTHY = "rtsp://192.168.1.50:554/stream1"
INSECURE = "rtsp://127.0.0.1:554/stream1"

OUTSIDE = (45.0, 20.0, 55.0, 40.0)  # bottom-centre y = 0.40 (above the entrance line)
INSIDE = (45.0, 40.0, 55.0, 60.0)  # bottom-centre y = 0.60 (below the entrance line)


class KeyedReports:
    """A per-camera report collector (the real ``report`` callback has no camera id)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_camera: dict[int, list[tuple[str, str | None, dict]]] = {}

    def collector(self, camera_id: int):
        def report(status: str, detail: str | None, metrics: dict) -> None:
            with self._lock:
                self._by_camera.setdefault(camera_id, []).append((status, detail, dict(metrics)))

        return report

    def snapshot(self, camera_id: int) -> list[tuple[str, str | None, dict]]:
        with self._lock:
            return list(self._by_camera.get(camera_id, []))

    def statuses(self, camera_id: int) -> list[str]:
        return [status for status, _detail, _metrics in self.snapshot(camera_id)]

    def report_metrics(self, camera_id: int, status: str) -> dict:
        with self._lock:
            for reported, _detail, metrics in self._by_camera.get(camera_id, []):
                if reported == status:
                    return metrics
        return {}


class BlockingDetector:
    """A detector whose ``detect`` blocks until a gate is released (a stuck camera)."""

    name = "blocking"

    def __init__(self, gate: threading.Event) -> None:
        self._gate = gate
        self.entered = threading.Event()
        self.closed = False

    def load(self) -> None:
        return None

    def detect(self, image: object) -> list[Detection]:
        self.entered.set()
        self._gate.wait(5.0)
        return []

    def close(self) -> None:
        self.closed = True


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


def _track(bbox: tuple[float, float, float, float], *, track_id: int = 1) -> Track:
    return Track(track_id=track_id, class_name="person", confidence=0.9, bbox=bbox)


def _config(
    camera_id: int,
    *,
    name: str | None = None,
    stream: str = HEALTHY,
    configuration: dict | None = None,
) -> CameraConfig:
    return CameraConfig(
        id=camera_id,
        name=name if name is not None else f"cam-{camera_id}",
        stream_reference=stream,
        configuration=configuration,
    )


def _build(
    camera: CameraConfig,
    *,
    reports: KeyedReports,
    source_factory=None,
    detector_factory=None,
    tracker_factory=None,
    event_sink=None,
) -> CameraWorker:
    if source_factory is None:
        source_factory = SourceFactory(
            lambda: FakeFrameSource([FakeImage()], block_when_exhausted=True)
        )
    if detector_factory is None:
        detector_factory = NullDetector
    if tracker_factory is None:
        tracker_factory = CountingTracker
    return CameraWorker(
        camera,
        settings=make_settings(),
        report=reports.collector(camera.id),
        source_factory=source_factory,
        detector_factory=detector_factory,
        tracker_factory=tracker_factory,
        event_sink=event_sink,
        logger=LOGGER,
    )


# --- failure isolation ----------------------------------------------------------


def test_a_terminal_failure_is_isolated_from_healthy_cameras() -> None:
    reports = KeyedReports()

    def make(camera: CameraConfig) -> CameraWorker:
        if camera.id == 2:
            return _build(_config(2, stream=INSECURE), reports=reports)
        if camera.id == 3:
            return _build(
                camera,
                reports=reports,
                detector_factory=lambda: ScriptedDetector(fail_load=True),
            )
        return _build(camera, reports=reports)

    manager = CameraManager(worker_factory=make, max_concurrent=3, stop_timeout=2.0)
    manager.ensure([_config(camera_id) for camera_id in (1, 2, 3)])
    try:
        assert wait_until(
            lambda: (
                "active" in reports.statuses(1)
                and "failed" in reports.statuses(2)
                and "failed" in reports.statuses(3)
            ),
            timeout=5.0,
        )
        # The healthy camera kept running while the others entered terminal failure.
        assert "failed" not in reports.statuses(1)
        assert reports.statuses(2)[-1] == "failed"
        assert reports.statuses(3)[-1] == "failed"
        # Terminal workers idle (threads alive) instead of hot-looping restarts.
        assert manager.running_ids() == [1, 2, 3]
        health = {item.camera_id: item for item in manager.health()}
        assert health[1].state in {CameraStatus.ACTIVE, CameraStatus.DEGRADED}
    finally:
        manager.shutdown()
    assert manager.running_ids() == []


def test_a_blocked_camera_does_not_block_another_camera() -> None:
    reports = KeyedReports()
    gate = threading.Event()
    blocking = BlockingDetector(gate)

    def make(camera: CameraConfig) -> CameraWorker:
        if camera.id == 2:
            return _build(camera, reports=reports, detector_factory=lambda: blocking)
        return _build(camera, reports=reports)

    manager = CameraManager(worker_factory=make, max_concurrent=2, stop_timeout=2.0)
    manager.ensure([_config(1), _config(2)])
    try:
        # Camera 2's detector is stuck inside ``detect`` for its frame.
        assert wait_until(blocking.entered.is_set, timeout=5.0)
        # Camera 1 still reaches ``active`` and processes frames independently.
        assert wait_until(lambda: "active" in reports.statuses(1), timeout=5.0)
        assert reports.report_metrics(1, "active").get("frames_processed", 0) >= 1
        # Camera 2 never reported ``active`` while blocked.
        assert "active" not in reports.statuses(2)
    finally:
        gate.set()
        manager.shutdown()


# --- event attribution ----------------------------------------------------------


def test_events_are_attributed_to_the_camera_that_produced_them() -> None:
    reports = KeyedReports()
    configuration = _entrance_configuration()
    first = CollectingSink()
    second = CollectingSink()
    worker1 = _build(_config(1, configuration=configuration), reports=reports, event_sink=first)
    worker2 = _build(_config(2, configuration=configuration), reports=reports, event_sink=second)

    # Deliver *interleaved* crossing frames to both cameras.
    worker1._observe_events(FakeImage(100, 100), [_track(OUTSIDE)], 0.0)
    worker2._observe_events(FakeImage(100, 100), [_track(INSIDE)], 0.0)
    worker1._observe_events(FakeImage(100, 100), [_track(INSIDE)], 1.0)
    worker2._observe_events(FakeImage(100, 100), [_track(OUTSIDE)], 1.0)

    # Camera 1 sees exactly its own inward crossing.
    assert first.event_types == ["person_entering", "person_entering"]
    assert {transition.event.camera_id for transition in first.transitions} == {1}
    # Camera 2 starts inside and then leaves.
    assert second.event_types == ["person_leaving", "person_leaving"]
    assert {transition.event.camera_id for transition in second.transitions} == {2}

    # Deterministic ids are camera-scoped: the two cameras never collide.
    first_ids = {transition.event.event_id for transition in first.transitions}
    second_ids = {transition.event.event_id for transition in second.transitions}
    assert first_ids.isdisjoint(second_ids)


# --- independent lifecycle ------------------------------------------------------


def test_manager_stops_only_the_requested_camera() -> None:
    reports = KeyedReports()
    created: dict[int, CameraWorker] = {}

    def make(camera: CameraConfig) -> CameraWorker:
        worker = _build(camera, reports=reports)
        created[camera.id] = worker
        return worker

    manager = CameraManager(worker_factory=make, max_concurrent=3, stop_timeout=2.0)
    manager.ensure([_config(1), _config(2)])
    try:
        assert wait_until(
            lambda: "active" in reports.statuses(1) and "active" in reports.statuses(2),
            timeout=5.0,
        )
        manager.stop(2)
        assert manager.running_ids() == [1]
        assert created[2].is_alive() is False
        assert created[1].is_alive() is True
        # The surviving camera is untouched.
        assert "disconnected" not in reports.statuses(1)
    finally:
        manager.shutdown()


def test_each_camera_reports_its_own_health() -> None:
    reports = KeyedReports()
    tracker = CountingTracker()
    manager = CameraManager(
        worker_factory=lambda camera: _build(
            camera, reports=reports, tracker_factory=lambda: tracker
        ),
        max_concurrent=2,
        stop_timeout=2.0,
    )
    manager.ensure([_config(5, name="a"), _config(9, name="b")])
    try:
        assert wait_until(
            lambda: all("active" in reports.statuses(cid) for cid in (5, 9)), timeout=5.0
        )
        health = {item.camera_id: item for item in manager.health()}
        assert set(health) == {5, 9}
        assert all(item.state is CameraStatus.ACTIVE for item in health.values())
        assert all(item.metrics["frames_processed"] >= 1 for item in health.values())
    finally:
        manager.shutdown()
