"""Shared, dependency-free fakes for the vision-worker tests."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from vision.config import VisionSettings
from vision.detection.detector import Detection
from vision.ingestion.sources import RawFrame
from vision.net import PinnedTarget


class FakeClock:
    """A manually advanced monotonic clock."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class FakeImage:
    """A stand-in for a decoded frame (shape + nbytes only)."""

    def __init__(self, height: int = 48, width: int = 64, channels: int = 3) -> None:
        self.shape = (height, width, channels)
        self.nbytes = height * width * channels


class FakeFrameSource:
    """A scripted frame source.

    ``frames`` are returned in order. When exhausted the source either blocks until
    :meth:`close` (a live stream that idles) or returns ``None`` (a stream that ended).
    """

    def __init__(
        self,
        frames: list[Any] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        open_result: bool = True,
        block_when_exhausted: bool = True,
        read_failure: bool = False,
    ) -> None:
        self._frames = list(frames or [])
        self._clock = clock
        self._open_result = open_result
        self._block = block_when_exhausted
        self._read_failure = read_failure
        self.closed = False
        self.reads = 0
        self._last: float | None = None
        self._closed = threading.Event()

    def open(self) -> bool:
        if self.closed:
            return False
        return self._open_result

    def read(self) -> RawFrame | None:
        if self.closed or self._read_failure:
            return None
        if self.reads < len(self._frames):
            image = self._frames[self.reads]
            self.reads += 1
            self._last = self._clock()
            return RawFrame(image=image, position_seconds=self.reads / 30.0)
        if self._block:
            self._closed.wait(5.0)
            return None
        return None

    def close(self) -> None:
        self.closed = True
        self._closed.set()

    @property
    def last_frame_monotonic(self) -> float | None:
        return self._last


class SourceFactory:
    """Records every source it creates (one per connection attempt)."""

    def __init__(self, factory: Callable[[], FakeFrameSource]) -> None:
        self._factory = factory
        self.created: list[FakeFrameSource] = []

    def __call__(self, target: PinnedTarget) -> FakeFrameSource:
        source = self._factory()
        self.created.append(source)
        return source


class ScriptedDetector:
    name = "scripted"

    def __init__(
        self,
        detections: list[Detection] | None = None,
        *,
        delay: float = 0.0,
        fail_load: bool = False,
    ) -> None:
        self._detections = list(detections or [])
        self._delay = delay
        self._fail_load = fail_load
        self.loaded = False
        self.closed = False

    def load(self) -> None:
        if self._fail_load:
            raise RuntimeError("no weights available")
        self.loaded = True

    def detect(self, image: Any) -> list[Detection]:
        if self._delay:
            time.sleep(self._delay)
        return list(self._detections)

    def close(self) -> None:
        self.closed = True


class CountingTracker:
    name = "counting"

    def __init__(self) -> None:
        self.resets = 0
        self.updates = 0

    def reset(self) -> None:
        self.resets += 1

    def update(self, detections: list[Detection]) -> list:
        self.updates += 1
        return []


class ReportCollector:
    """Collects ``(status, detail, metrics)`` tuples from a worker."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.reports: list[tuple[str, str | None, dict]] = []

    def __call__(self, status: str, detail: str | None, metrics: dict) -> None:
        with self._lock:
            self.reports.append((status, detail, dict(metrics)))

    def statuses(self) -> list[str]:
        with self._lock:
            return [report[0] for report in self.reports]

    def snapshot(self) -> list[tuple[str, str | None, dict]]:
        with self._lock:
            return list(self.reports)

    def first_index(self, status: str) -> int:
        with self._lock:
            for index, report in enumerate(self.reports):
                if report[0] == status:
                    return index
        return -1

    def report_metrics(self, status: str) -> dict:
        with self._lock:
            for report in self.reports:
                if report[0] == status:
                    return report[2]
        return {}


def wait_until(
    predicate: Callable[[], bool], *, timeout: float = 4.0, interval: float = 0.01
) -> bool:
    """Poll ``predicate`` until it is truthy or ``timeout`` elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def write_test_video(
    path,
    *,
    frames: int = 12,
    width: int = 64,
    height: int = 48,
    fps: float = 10.0,
) -> str:
    """Write a tiny synthetic MJPG/AVI clip. Requires OpenCV + NumPy (caller skips)."""
    import cv2  # lazy: importing fakes must not require OpenCV
    import numpy as np

    fourcc = cv2.VideoWriter_fourcc(*"MJPG")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (width, height))
    if not writer.isOpened():  # pragma: no cover - codec dependent
        raise RuntimeError("could not open a video writer for the test clip")
    try:
        for index in range(frames):
            frame = np.full((height, width, 3), index * 4 % 255, dtype=np.uint8)
            writer.write(frame)
    finally:
        writer.release()
    return str(path)


def make_settings(**overrides: Any) -> VisionSettings:
    """Test vision settings with fast, deterministic timings."""
    values: dict[str, Any] = {
        "poll_interval_seconds": 0.05,
        "heartbeat_interval_seconds": 1.0,
        "connect_timeout_seconds": 0.2,
        "read_timeout_seconds": 30.0,
        "reconnect_initial_backoff_seconds": 0.01,
        "reconnect_max_backoff_seconds": 0.05,
        "queue_maxsize": 8,
        "process_target_fps": 1000.0,
        "degraded_window_frames": 1000,
    }
    values.update(overrides)
    return VisionSettings(**values)
