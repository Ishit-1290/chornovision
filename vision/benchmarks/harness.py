"""Benchmarking harness for the vision worker (Phase 8; NFR-13, NFR-15, G §16.3).

Phase 8 must establish a one-camera baseline and measure how the pipeline scales before any
promise about multiple cameras is made. This module provides **reproducible, dependency-light
benchmarks** that run the *real* `CameraWorker`/`CameraManager` threading model with a
**real OpenCV decode** of a generated clip and a **simulated detector** whose per-frame cost is
configurable (so the detector's CPU cost can be modelled without YOLO weights*).

It measures the runtime metrics G §16.3 calls for: capture vs. processed FPS, frame-processing
latency p50/p95/p99, bounded-queue depth and drops, startup time, and process RSS/CPU. Two
focused micro-benchmarks measure the event-handoff delivery latency and snapshot-encode cost.

Everything here is deterministic in shape (fixed clip, fixed sampling, fixed detector cost).
Timing numbers are inherently machine-dependent and are reported as measured, never asserted as
a performance guarantee. `run_camera_benchmark` needs OpenCV + NumPy; the module imports them
lazily so importing it never requires them.

* A real-YOLO mode is intentionally not automated here: no weights ship with the repository and
  `vision.detector_weights` may download on first use. The harness records the configured
  detector mode so a real run can be reproduced by pointing `detector` at `YoloDetector`.
"""

from __future__ import annotations

import json
import logging
import math
import os
import resource
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.events.types import EventTransition

from vision.camera_manager.manager import CameraManager
from vision.camera_manager.worker import CameraConfig, CameraWorker
from vision.config import VisionSettings
from vision.detection.detector import Detection
from vision.event_handoff import EventHandoff
from vision.evidence.store import EvidenceStore
from vision.ingestion.sources import RawFrame
from vision.tracking.tracker import IoUTracker

LOGGER = logging.getLogger("vision.benchmarks")


# --- helpers --------------------------------------------------------------------


def percentiles_ms(samples: list[float]) -> dict[str, float | int | None]:
    """Nearest-rank percentiles (milliseconds) over ``samples`` (already in ms)."""
    if not samples:
        return {
            "count": 0,
            "min_ms": None,
            "p50_ms": None,
            "p95_ms": None,
            "p99_ms": None,
            "max_ms": None,
        }
    ordered = sorted(samples)
    count = len(ordered)

    def rank(fraction: float) -> float:
        index = max(0, min(count - 1, math.ceil(fraction * count) - 1))
        return round(ordered[index], 3)

    return {
        "count": count,
        "min_ms": round(ordered[0], 3),
        "p50_ms": rank(0.50),
        "p95_ms": rank(0.95),
        "p99_ms": rank(0.99),
        "max_ms": round(ordered[-1], 3),
    }


def read_rss_mb() -> float | None:
    """Resident set size in MiB (Linux ``/proc/self/statm``), or ``None`` if unavailable."""
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            fields = handle.read().split()
        resident_pages = int(fields[1])
        page_size = os.sysconf("SC_PAGE_SIZE")
        return round(resident_pages * page_size / (1024 * 1024), 2)
    except (OSError, ValueError, IndexError):  # pragma: no cover - platform dependent
        return None


def cpu_seconds() -> float:
    """Cumulative process CPU time (user + system) in seconds."""
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime + usage.ru_stime


def environment_info() -> dict[str, Any]:
    """Non-sensitive environment descriptors so a benchmark run is reproducible."""
    info: dict[str, Any] = {
        "cpu_count": os.cpu_count(),
        "platform": os.uname().machine if hasattr(os, "uname") else "unknown",
        "python": os.sys.version.split()[0],
    }
    try:
        import cv2  # lazy

        info["opencv"] = cv2.__version__
    except Exception:  # pragma: no cover - optional dependency
        info["opencv"] = None
    info["gpu"] = gpu_info()
    return info


def gpu_info() -> dict[str, Any]:
    """Report GPU/CUDA availability, or an explicit "unavailable" record.

    Detection can run on CPU or GPU. When no CUDA-capable device (or no PyTorch) is present
    the harness records that honestly with ``available: False`` rather than omitting the field,
    so a reader can tell "GPU not measured" apart from "GPU measured as absent".
    """
    try:
        import torch  # lazy
    except Exception:  # pragma: no cover - torch is optional for the harness
        return {
            "available": False,
            "reason": "torch_not_installed",
            "device": None,
            "torch": None,
            "total_memory_mb": None,
        }
    info: dict[str, Any] = {
        "available": False,
        "reason": None,
        "device": None,
        "torch": torch.__version__,
        "cuda_build": getattr(torch.version, "cuda", None),
        "total_memory_mb": None,
    }
    try:
        if torch.cuda.is_available():
            info["available"] = True
            info["device"] = torch.cuda.get_device_name(0)
            props = torch.cuda.get_device_properties(0)
            info["total_memory_mb"] = round(props.total_memory / (1024 * 1024), 1)
        else:
            info["reason"] = "cuda_not_available"
    except Exception as exc:  # pragma: no cover - driver/runtime dependent
        info["reason"] = f"cuda_query_failed: {type(exc).__name__}"
    return info


# --- synthetic components -------------------------------------------------------


def build_clip(
    path: Path,
    *,
    frames: int = 300,
    width: int = 640,
    height: int = 480,
    fps: float = 30.0,
) -> str:
    """Write a tiny synthetic MJPG/AVI clip and return its path (needs OpenCV + NumPy)."""
    import cv2
    import numpy as np

    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (width, height))
    if not writer.isOpened():  # pragma: no cover - codec dependent
        raise RuntimeError("could not open a video writer for the benchmark clip")
    try:
        for index in range(frames):
            frame = np.full((height, width, 3), (index * 7) % 255, dtype=np.uint8)
            writer.write(frame)
    finally:
        writer.release()
    return str(path)


class LoopingClipSource:
    """A real OpenCV decode of a local clip, paced to a camera-like frame rate.

    A real RTSP camera delivers frames at a fixed rate; decoding a local file as fast as
    possible is both unrepresentative and unstable (many decoders hammering the same tiny clip
    and rewinding). This source therefore paces reads to ``capture_fps`` and loops by
    *reopening* the file at end-of-clip rather than seeking, which keeps many concurrent
    decoders stable while still exercising the real OpenCV/FFmpeg decode path.
    """

    def __init__(
        self,
        source: str,
        *,
        capture_fps: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._source = source
        self._capture_fps = max(0.0, capture_fps)
        self._clock = clock
        self._cap: Any | None = None
        self._last: float | None = None
        self._closed = True
        self._next_due = 0.0
        self._lock = threading.Lock()

    def _open_cap(self) -> Any | None:
        import cv2

        cap = cv2.VideoCapture(self._source, cv2.CAP_FFMPEG)
        if not cap.isOpened():
            cap.release()
            return None
        return cap

    def open(self) -> bool:
        cap = self._open_cap()
        with self._lock:
            self._cap = cap
            self._closed = cap is None
            self._next_due = self._clock()
            self._last = None
        return cap is not None

    def read(self) -> RawFrame | None:
        import cv2

        self._pace()
        with self._lock:
            cap = self._cap
            if self._closed or cap is None:
                return None
            ok, frame = cap.read()
            if not ok or frame is None:
                # Loop by reopening instead of seeking (stable under many concurrent decoders).
                cap.release()
                cap = self._open_cap()
                self._cap = cap
                if cap is None:
                    self._closed = True
                    return None
                ok, frame = cap.read()
                if not ok or frame is None:
                    return None
            self._last = self._clock()
            position: float | None = None
            try:
                msec = float(cap.get(cv2.CAP_PROP_POS_MSEC))
                position = msec / 1000.0 if msec > 0 else None
            except Exception:  # pragma: no cover - backend dependent
                position = None
        return RawFrame(image=frame, position_seconds=position)

    def _pace(self) -> None:
        """Sleep until the next frame is due, staying responsive to ``close``."""
        if self._capture_fps <= 0:
            return
        delay = self._next_due - self._clock()
        while delay > 0 and not self._closed:
            time.sleep(min(delay, 0.05))
            delay = self._next_due - self._clock()
        self._next_due = max(self._clock(), self._next_due) + 1.0 / self._capture_fps

    def close(self) -> None:
        with self._lock:
            self._closed = True
            cap = self._cap
            self._cap = None
        if cap is not None:
            try:
                cap.release()
            except Exception:  # pragma: no cover
                pass

    @property
    def last_frame_monotonic(self) -> float | None:
        return self._last


class SyntheticDetector:
    """A detector with a fixed per-frame cost (models CPU inference) and fixed detections.

    Keras/Torch inference cost is not reproducible across machines, so the benchmark makes the
    per-frame detector cost an explicit input. This keeps the *pipeline* overhead measurable
    independently of the model. It never downloads weights.
    """

    name = "synthetic"

    def __init__(
        self,
        *,
        cost_seconds: float = 0.0,
        detections: list[Detection] | None = None,
    ) -> None:
        self._cost = max(0.0, cost_seconds)
        self._detections = list(detections or [])
        self.loaded = False

    def load(self) -> None:
        self.loaded = True

    def detect(self, image: Any) -> list[Detection]:
        if self._cost:
            time.sleep(self._cost)
        return list(self._detections)

    def close(self) -> None:
        return None


@dataclass
class BenchmarkConfig:
    """Inputs for one multi-camera runtime benchmark."""

    camera_count: int = 1
    duration_seconds: float = 10.0
    process_target_fps: float = 10.0
    process_width: int = 0
    detector_cost_seconds: float = 0.02
    queue_maxsize: int = 8
    latency_sample_capacity: int = 4096
    clip_frames: int = 300
    clip_width: int = 640
    clip_height: int = 480
    clip_fps: float = 30.0
    #: Simulated camera capture rate (frames read per second by the synthetic source).
    capture_fps: float = 30.0


class _Recorder:
    """Collects per-camera lifecycle transitions and the latest metrics snapshot."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.states: dict[int, str] = {}
        self.first_active: dict[int, float] = {}
        self.active_times: list[float] = []
        self.last_metrics: dict[int, dict[str, object]] = {}

    def bind(self, camera_id: int) -> Callable[[str, str | None, dict[str, object]], None]:
        def report(status: str, detail: str | None, metrics: dict[str, object]) -> None:
            now = time.monotonic()
            with self._lock:
                self.states[camera_id] = status
                if status == "active":
                    self.active_times.append(now)
                    self.first_active.setdefault(camera_id, now)
                self.last_metrics[camera_id] = dict(metrics)

        return report

    def first_active_seconds(self, reference: float) -> float | None:
        with self._lock:
            if not self.first_active:
                return None
            return round(min(self.first_active.values()) - reference, 3)

    def all_active_seconds(self, reference: float, count: int) -> float | None:
        with self._lock:
            if len(self.first_active) < count:
                return None
            return round(max(self.first_active.values()) - reference, 3)

    def active_times_after(self, reference: float) -> list[float]:
        """Return every ``active`` report time strictly after ``reference`` (monotonic)."""
        with self._lock:
            return [value for value in self.active_times if value > reference]


def run_camera_benchmark(
    config: BenchmarkConfig,
    *,
    clip_path: str | None = None,
    workdir: Path | None = None,
) -> dict[str, Any]:
    """Run ``camera_count`` real workers for ``duration_seconds`` and return measured metrics.

    Requires OpenCV + NumPy (the clip is decoded for real). Raises :class:`RuntimeError` if the
    clip cannot be created.
    """
    if clip_path is None:
        if workdir is None:  # pragma: no cover - caller error
            raise ValueError("either clip_path or workdir must be provided")
        clip_path = build_clip(
            Path(workdir) / "benchmark-clip.avi",
            frames=config.clip_frames,
            width=config.clip_width,
            height=config.clip_height,
            fps=config.clip_fps,
        )

    settings = VisionSettings(
        poll_interval_seconds=1.0,
        connect_timeout_seconds=5.0,
        read_timeout_seconds=5.0,
        queue_maxsize=config.queue_maxsize,
        process_target_fps=config.process_target_fps,
        process_width=config.process_width,
        metrics_latency_sample_capacity=config.latency_sample_capacity,
        rolling_buffer_frames=1,
        reconnect_max_attempts=0,
    )
    recorder = _Recorder()

    def worker_factory(camera: CameraConfig) -> CameraWorker:
        return CameraWorker(
            camera,
            settings=settings,
            report=recorder.bind(camera.id),
            source_factory=lambda _target: LoopingClipSource(
                clip_path, capture_fps=config.capture_fps
            ),
            detector_factory=lambda: SyntheticDetector(cost_seconds=config.detector_cost_seconds),
            tracker_factory=IoUTracker,
            logger=LOGGER,
        )

    manager = CameraManager(
        worker_factory=worker_factory,
        max_concurrent=config.camera_count,
        stop_timeout=settings.connect_timeout_seconds + 5.0,
        logger=LOGGER,
    )
    # The streaming source is the local clip (the ``source_factory`` decodes it directly), but
    # the reference must still pass the worker's connection-time SSRF validation, so it uses an
    # allowed RTSP literal rather than a ``file://`` URL.
    stream_reference = "rtsp://192.168.1.50:554/benchmark"
    cameras = [
        CameraConfig(
            id=camera_id,
            name=f"bench-{camera_id}",
            stream_reference=stream_reference,
        )
        for camera_id in range(1, config.camera_count + 1)
    ]

    rss_start = read_rss_mb()
    cpu_start = cpu_seconds()
    reference = time.monotonic()
    wall_start = time.perf_counter()
    manager.ensure(cameras)
    try:
        deadline = reference + config.duration_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.1, remaining))
        health = {item.camera_id: item for item in manager.health()}
        startup = recorder.first_active_seconds(reference)
        all_active = recorder.all_active_seconds(reference, config.camera_count)
    finally:
        manager.shutdown()
    wall_seconds = time.perf_counter() - wall_start
    rss_end = read_rss_mb()
    cpu_used = cpu_seconds() - cpu_start

    per_camera: list[dict[str, Any]] = []
    totals = {
        "frames_received": 0,
        "frames_processed": 0,
        "frames_skipped": 0,
        "frames_dropped": 0,
        "events_emitted": 0,
    }
    for camera_id in sorted(health):
        metrics = health[camera_id].metrics
        for key in totals:
            totals[key] += int(metrics.get(key, 0) or 0)
        per_camera.append(
            {
                "camera_id": camera_id,
                "state": str(health[camera_id].state.value),
                "frames_received": metrics.get("frames_received"),
                "frames_processed": metrics.get("frames_processed"),
                "ingest_fps": metrics.get("ingest_fps"),
                "process_fps": metrics.get("process_fps"),
                "queue_max_depth": metrics.get("queue_max_depth"),
                "frames_dropped": metrics.get("frames_dropped"),
                "latency_p50_ms": metrics.get("latency_p50_ms"),
                "latency_p95_ms": metrics.get("latency_p95_ms"),
                "latency_p99_ms": metrics.get("latency_p99_ms"),
                "latency_sample_count": metrics.get("latency_sample_count"),
            }
        )

    aggregate_fps = round(totals["frames_processed"] / wall_seconds, 3) if wall_seconds else 0.0
    return {
        "config": asdict(config),
        "environment": environment_info(),
        "detector_mode": "synthetic",
        "wall_seconds": round(wall_seconds, 3),
        "startup_seconds": startup,
        "all_active_seconds": all_active,
        "camera_count": config.camera_count,
        "totals": {**totals, "process_fps": aggregate_fps},
        "cameras": per_camera,
        "resources": {
            "rss_mb_start": rss_start,
            "rss_mb_end": rss_end,
            "rss_delta_mb": (
                round(rss_end - rss_start, 2)
                if rss_start is not None and rss_end is not None
                else None
            ),
            "cpu_seconds": round(cpu_used, 3),
            "cpu_percent": (round(cpu_used / wall_seconds * 100.0, 2) if wall_seconds else None),
        },
    }


# --- micro-benchmarks -----------------------------------------------------------


class _Outage:
    """A shared, thread-safe simulated camera outage window (monotonic seconds)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._until = 0.0

    def begin(self, seconds: float) -> float:
        """Start an outage of ``seconds`` and return the monotonic start time."""
        start = time.monotonic()
        with self._lock:
            self._until = start + max(0.0, seconds)
        return start

    def recovering(self) -> bool:
        with self._lock:
            return time.monotonic() < self._until


class _GatedClipSource(LoopingClipSource):
    """A clip source that reports the stream down (``read() -> None``) during an outage."""

    def __init__(self, source: str, *, outage: _Outage, capture_fps: float = 30.0) -> None:
        super().__init__(source, capture_fps=capture_fps)
        self._outage = outage

    def read(self) -> RawFrame | None:
        if self._outage.recovering():
            return None
        return super().read()


def measure_recovery_time(
    *,
    clip_path: str | None = None,
    workdir: Path | None = None,
    outage_seconds: float = 1.0,
    capture_fps: float = 30.0,
    process_target_fps: float = 10.0,
    timeout_seconds: float = 15.0,
) -> dict[str, Any]:
    """Measure how long a real worker takes to return to ``active`` after a dropped stream.

    A one-camera worker runs normally; then its source is forced down for ``outage_seconds``
    (every ``read`` returns ``None``), which drives the real ``active → disconnected →
    reconnecting → connecting → active`` path. Recovery is measured from the start of the
    outage to the next ``active`` report, and the reconnect overhead is that minus the outage
    itself. Requires OpenCV + NumPy (real decode).
    """
    if clip_path is None:
        if workdir is None:  # pragma: no cover - caller error
            raise ValueError("either clip_path or workdir must be provided")
        clip_path = build_clip(Path(workdir) / "recovery-clip.avi", frames=150)

    settings = VisionSettings(
        poll_interval_seconds=0.5,
        connect_timeout_seconds=5.0,
        read_timeout_seconds=5.0,
        process_target_fps=process_target_fps,
        reconnect_initial_backoff_seconds=0.1,
        reconnect_max_backoff_seconds=0.5,
        reconnect_max_attempts=0,
        rolling_buffer_frames=1,
    )
    outage = _Outage()
    recorder = _Recorder()
    worker_factory = lambda camera: CameraWorker(  # noqa: E731
        camera,
        settings=settings,
        report=recorder.bind(camera.id),
        source_factory=lambda _target: _GatedClipSource(
            clip_path, outage=outage, capture_fps=capture_fps
        ),
        detector_factory=lambda: SyntheticDetector(cost_seconds=0.0),
        tracker_factory=IoUTracker,
        logger=LOGGER,
    )
    manager = CameraManager(
        worker_factory=worker_factory,
        max_concurrent=1,
        stop_timeout=settings.connect_timeout_seconds + 5.0,
        logger=LOGGER,
    )
    camera = CameraConfig(id=1, name="recovery", stream_reference="rtsp://192.168.1.51:554/bench")

    recovered = False
    recovery_seconds: float | None = None
    result: dict[str, Any] = {
        "outage_seconds": outage_seconds,
        "recovered": False,
        "recovery_seconds": None,
        "reconnect_overhead_seconds": None,
    }
    try:
        manager.ensure([camera])
        # Wait for the first active report before starting the outage.
        ready_deadline = time.monotonic() + timeout_seconds
        while not recorder.first_active and time.monotonic() < ready_deadline:
            time.sleep(0.02)
        if not recorder.first_active:  # pragma: no cover - startup should succeed
            result["error"] = "worker did not become active before the outage"
            return result

        outage_start = outage.begin(outage_seconds)
        deadline = outage_start + outage_seconds + timeout_seconds
        while time.monotonic() < deadline:
            later = recorder.active_times_after(outage_start)
            if later:
                recovered = True
                recovery_seconds = round(min(later) - outage_start, 3)
                break
            time.sleep(0.02)
    finally:
        manager.shutdown()

    result["recovered"] = recovered
    result["recovery_seconds"] = recovery_seconds
    result["reconnect_overhead_seconds"] = (
        round(max(0.0, recovery_seconds - outage_seconds), 3)
        if recovery_seconds is not None
        else None
    )
    return result


class _RecordingInternalClient:
    """A no-network stand-in for ``InternalClient`` that timestamps delivery."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.delivered_at: dict[str, float] = {}
        self.deliveries = 0
        self.errors: list[str] = []

    def _record(self, key: str) -> None:
        with self._lock:
            self.deliveries += 1
            # Keep the *first* delivery time for a key so latency reflects the first publish.
            self.delivered_at.setdefault(key, time.perf_counter())

    def submit_event(self, payload: dict[str, Any]) -> None:
        self._record(str(payload["event"]["event_id"]))

    def register_evidence(self, event_id: str, payload: dict[str, Any]) -> None:
        self._record(str(payload["event_id"]))


def _transition(event_id: str, camera_id: int) -> EventTransition:
    from app.events.types import (
        Certainty,
        EventAction,
        EventSeverity,
        EventSnapshot,
        EventStatus,
        EventType,
    )

    now = datetime.now(UTC)
    snapshot = EventSnapshot(
        event_id=event_id,
        camera_id=camera_id,
        event_type=EventType.PERSON_ENTERING,
        start_time=now,
        trigger_time=now,
        last_updated_at=now,
        status=EventStatus.ACTIVE,
        severity=EventSeverity.INFO,
        state_version=1,
        certainty=Certainty.HIGH,
    )
    return EventTransition(action=EventAction.OPENED, event=snapshot)


def measure_event_handoff_latency(
    *,
    count: int = 200,
    spool_dir: Path,
    camera_id: int = 1,
    queue_maxsize: int | None = None,
) -> dict[str, Any]:
    """Measure enqueue→delivered latency of the bounded event handoff (no network)."""
    client = _RecordingInternalClient()
    handoff = EventHandoff(
        client=client,  # type: ignore[arg-type]
        camera_id=camera_id,
        queue_maxsize=queue_maxsize or (count + 1),
        spool_dir=spool_dir,
        max_attempts=1,
        retry_backoff_seconds=0.0,
    )
    enqueued_at: dict[str, float] = {}
    for index in range(count):
        event_id = f"bench-{index:05d}"
        enqueued_at[event_id] = time.perf_counter()
        handoff.enqueue_event(_transition(event_id, camera_id))

    flushed = handoff.flush(timeout=10.0)
    latencies = [
        (client.delivered_at[event_id] - enqueued_at[event_id]) * 1000.0
        for event_id in enqueued_at
        if event_id in client.delivered_at
    ]
    counters = handoff.counters()
    handoff.shutdown()
    duplicate_deliveries = max(0, client.deliveries - len(client.delivered_at))
    return {
        "requested": count,
        "delivered": len(latencies),
        "deliveries_total": client.deliveries,
        "duplicate_deliveries": duplicate_deliveries,
        "duplication_rate": round(duplicate_deliveries / count, 4) if count else None,
        "flushed": flushed,
        "dropped": counters["dropped"],
        "spooled": counters["spooled"],
        "latency": percentiles_ms(latencies),
    }


def measure_evidence_encode_latency(
    *,
    root: Path,
    count: int = 20,
    width: int = 640,
    height: int = 480,
) -> dict[str, Any]:
    """Measure snapshot encode+write latency (real OpenCV JPEG encode). Needs OpenCV + NumPy."""
    import numpy as np

    store = EvidenceStore(root=root)
    image = np.full((height, width, 3), 128, dtype=np.uint8)
    samples: list[float] = []
    last_size = 0
    for index in range(count):
        started = time.perf_counter()
        record = store.save_snapshot(
            camera_id=1,
            event_id=f"bench-{index:05d}",
            captured_at=datetime.now(UTC),
            image=image,
        )
        samples.append((time.perf_counter() - started) * 1000.0)
        if record.file_size_bytes:
            last_size = record.file_size_bytes
    return {
        "count": count,
        "width": width,
        "height": height,
        "jpeg_bytes": last_size,
        "latency": percentiles_ms(samples),
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    """Persist a benchmark report as pretty JSON."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(report, indent=2, sort_keys=False), encoding="utf-8")
