"""One camera, one worker thread (FR-02, FR-06 groundwork, NFR-02).

:class:`CameraWorker` owns a single camera's lifecycle end to end:

    connecting -> active <-> degraded
    connecting/active/degraded -> disconnected -> reconnecting -> connecting -> ...

A camera is reported ``active`` only after a real connection delivered at least one
*decodable* frame that was processed (detection + tracking ran), so the backend can never
claim a camera is running when nothing is processed (D-24).

Threading model
---------------
* The **worker thread** owns lifecycle state and runs the processing loop.
* A **capture thread** decodes frames and pushes sampled frames into a bounded queue.

Both threads are created by :meth:`start` and torn down by :meth:`stop`; there is no
unmanaged background task. A failing camera only ends *its own* worker (FR-06 groundwork);
multi-*process* isolation is deferred to Phase 8.

Failure handling
----------------
* Unresolvable/insecure targets, an unloadable detector, and exhausted reconnect attempts
  are *terminal*: the worker reports ``failed`` and then idles until stopped, so the manager
  does not hot-loop restarting it. Changing the desired plan (stop/start monitoring) stops
  and recreates the worker.
* An unavailable camera, a stalled stream, or a read error is *recoverable*: the worker
  reports ``disconnected`` → ``reconnecting`` and retries with capped exponential backoff.
* On every (re)connection the tracker is reset so tracks are never carried across a gap
  (FR-08).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from app.config import get_settings
from app.events.zones import CameraRulesError
from app.models.camera import CameraStatus

from vision.buffer import RollingFrameBuffer
from vision.config import VisionSettings
from vision.detection.detector import Detection, Detector
from vision.event_engine import (
    EngineFrame,
    EntityObservation,
    EventSink,
    TemporalEventEngine,
    build_engine,
)
from vision.health import (
    DETAIL_BACKOFF,
    DETAIL_DETECTOR_LOAD_FAILED,
    DETAIL_INSECURE_TARGET,
    DETAIL_OPEN_FAILED,
    DETAIL_READ_FAILED,
    DETAIL_RECONNECT_EXHAUSTED,
    DETAIL_REQUESTED,
    DETAIL_STREAM_STALLED,
    WorkerHealth,
)
from vision.ingestion.prepare import SamplingPolicy, is_valid_frame, prepare_frame
from vision.ingestion.queue import FrameQueue
from vision.ingestion.rotation import map_bbox_from_rotated, normalize_rotation, rotate_frame
from vision.ingestion.sources import Frame, FrameSource, RawFrame, tag_frame
from vision.metrics import StreamMetrics
from vision.net import PinnedTarget, StreamSecurityError, resolve_and_validate
from vision.tracking.tracker import Track, Tracker

LOGGER = logging.getLogger("vision.camera_worker")

#: Callback the worker uses to report a state change to the backend.
ReportFn = Callable[[str, "str | None", "dict[str, object]"], None]
SourceFactory = Callable[[PinnedTarget], FrameSource]
DetectorFactory = Callable[[], Detector]
TrackerFactory = Callable[[], Tracker]


class EvidenceCapture(Protocol):
    """The worker-facing slice of the Phase 6 evidence coordinator."""

    def bind_buffer(self, buffer: Any) -> None: ...

    def on_frame(self, frame: Any, monotonic: float | None = None) -> None: ...

    def on_stream_end(self, monotonic: float | None = None) -> None: ...

    def reset(self) -> None: ...

    def shutdown(self, timeout: float = 5.0) -> None: ...

    def counters(self) -> dict[str, int]: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


class DetectorUnavailable(RuntimeError):
    """The detector could not be loaded (terminal for the current worker)."""


@dataclass(frozen=True)
class CameraConfig:
    """The subset of camera configuration a worker needs."""

    id: int
    name: str
    stream_reference: str
    enabled: bool = True
    #: Raw camera ``configuration`` JSON (zones, event rules). Validated by the engine.
    configuration: dict[str, Any] | None = None


@dataclass
class FrameObservation:
    """A processed frame plus the tracks observed on it (Phase 5 input)."""

    camera_id: int
    position_seconds: float | None
    arrival_utc: datetime
    image: Any
    tracks: list[Track]
    #: Monotonic capture time, used to bound the evidence pre-event window.
    monotonic: float = 0.0


class CameraWorker:
    """A single-camera ingestion/detection/tracking worker."""

    def __init__(
        self,
        camera: CameraConfig,
        *,
        settings: VisionSettings,
        report: ReportFn,
        source_factory: SourceFactory,
        detector_factory: DetectorFactory,
        tracker_factory: TrackerFactory,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = _utcnow,
        event_sink: EventSink | None = None,
        evidence: EvidenceCapture | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._camera = camera
        #: Detection-time frame rotation (see vision.ingestion.rotation). 0 when unset.
        self._rotation = normalize_rotation((camera.configuration or {}).get("rotation"))
        self._settings = settings
        self._report_fn = report
        self._source_factory = source_factory
        self._detector_factory = detector_factory
        self._tracker_factory = tracker_factory
        self._clock = clock
        self._wall_clock = wall_clock
        self._logger = logger or LOGGER
        self._evidence = evidence

        self._engine: TemporalEventEngine | None = None
        try:
            self._engine = build_engine(
                camera.id,
                camera.configuration,
                event_sink=event_sink,
                logger=self._logger,
            )
        except CameraRulesError as exc:
            # A camera with invalid rules still processes frames; its event rules stay off.
            self._logger.warning("camera %s: invalid event configuration: %s", camera.id, exc)
        self._event_lock = threading.Lock()
        self._events_emitted = 0
        self._event_errors = 0

        self._queue = FrameQueue(settings.queue_maxsize, clock=clock)
        self._buffer = RollingFrameBuffer(
            self._rolling_buffer_items(),
            settings.rolling_buffer_max_mb * 1024 * 1024,
        )
        if evidence is not None:
            # The manager pulls its pre-event window from this same bounded buffer.
            evidence.bind_buffer(self._buffer)
        self._metrics = StreamMetrics(
            clock=clock,
            latency_sample_capacity=settings.metrics_latency_sample_capacity,
        )
        self._sampling = SamplingPolicy(settings.process_target_fps, clock=clock)

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._source_lock = threading.Lock()
        self._model_lock = threading.Lock()

        self._state = CameraStatus.CONFIGURED
        self._detail: str | None = None
        self._last_report = clock()
        self._source: FrameSource | None = None
        self._capture_thread: threading.Thread | None = None
        self._capture_done = False
        self._capture_error: str | None = None
        self._session_start = clock()
        self._last_detail: str | None = None

        self._detector: Detector | None = None
        self._tracker: Tracker | None = None

        # Degradation window bookkeeping.
        self._degrade_processed = 0
        self._degrade_received = 0
        self._degrade_dropped = 0

    # -- public lifecycle ----------------------------------------------------------
    @property
    def camera_id(self) -> int:
        return self._camera.id

    @property
    def config(self) -> CameraConfig:
        """The camera configuration this worker was created for (FR-47 reconciliation).

        The manager compares this against the latest requested configuration so an edited
        camera (zones/rules/stream) is restarted rather than left running stale rules.
        """
        return self._camera

    @property
    def state(self) -> CameraStatus:
        return self._state

    def start(self) -> None:
        """Start the worker thread (idempotent while alive)."""
        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name=f"cv-camera-{self._camera.id}", daemon=True
            )
            self._thread.start()

    def stop(self, timeout: float | None = None) -> None:
        """Request shutdown, release the source, and join the worker thread."""
        self._stop.set()
        self._queue.wake()
        self._close_source()
        thread = self._thread
        if thread is not None and thread.is_alive():
            join_timeout = (
                timeout if timeout is not None else self._settings.connect_timeout_seconds
            )
            thread.join(timeout=join_timeout)
        self._release_models()
        if self._evidence is not None:
            # Flush captures/evidence delivery once the frame loop has stopped.
            self._evidence.shutdown()

    def is_alive(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def health(self) -> WorkerHealth:
        """Return a point-in-time, non-sensitive health snapshot."""
        return WorkerHealth(
            camera_id=self._camera.id,
            state=self._state,
            detail=self._detail,
            metrics=self._payload(),
        )

    # -- reporting -----------------------------------------------------------------
    def _payload(self) -> dict[str, object]:
        payload = self._metrics.snapshot()
        payload["queue_depth"] = self._queue.depth
        payload["queue_max_depth"] = self._queue.max_depth
        payload["frames_dropped"] = self._queue.dropped
        with self._event_lock:
            payload["events_emitted"] = self._events_emitted
            payload["event_errors"] = self._event_errors
        if self._evidence is not None:
            try:
                payload.update(self._evidence.counters())
            except Exception:  # metrics must never break a health report
                self._logger.warning("camera %s: evidence counters failed", self._camera.id)
        return payload

    def _rolling_buffer_items(self) -> int:
        """Frame count for the rolling buffer (derived from the evidence window if unset)."""
        configured = self._settings.rolling_buffer_frames
        if configured is not None:
            return max(1, int(configured))
        seconds = float(get_settings().evidence_rolling_buffer_seconds)
        return max(1, math.ceil(seconds * self._settings.process_target_fps) + 1)

    def _report(
        self, status: CameraStatus, detail: str | None = None, *, force: bool = False
    ) -> None:
        with self._state_lock:
            if not force and status is self._state and detail == self._detail:
                return
            self._state = status
            self._detail = detail
            self._last_report = self._clock()
        self._emit(status, detail)

    def _emit(self, status: CameraStatus, detail: str | None) -> None:
        try:
            self._report_fn(status.value, detail, self._payload())
        except Exception:  # reporting must never crash the worker
            self._logger.warning(
                "camera %s: failed to report state %s", self._camera.id, status.value
            )

    def _maybe_heartbeat(self) -> None:
        with self._state_lock:
            due = (self._clock() - self._last_report) >= self._settings.heartbeat_interval_seconds
            state, detail = self._state, self._detail
        if due:
            self._report(state, detail, force=True)

    def _terminal(self, status: CameraStatus, detail: str) -> None:
        """Report a terminal state and idle until stopped (no restart churn)."""
        self._report(status, detail)
        self._release_models()
        self._stop.wait()

    # -- source management ---------------------------------------------------------
    def _build_source(self, target: PinnedTarget) -> FrameSource:
        if not target.pinned:
            # Documented residual (D-22): the decoder re-resolves; log only the vhost mode.
            self._logger.warning(
                "camera %s: stream host mode disabled destination pinning", self._camera.id
            )
        return self._source_factory(target)

    def _set_source(self, source: FrameSource) -> None:
        with self._source_lock:
            self._source = source

    def _close_source(self) -> None:
        with self._source_lock:
            source = self._source
            self._source = None
        if source is not None:
            try:
                source.close()
            except Exception:  # pragma: no cover - release is best-effort
                pass

    # -- models --------------------------------------------------------------------
    def _ensure_detector(self) -> Detector:
        with self._model_lock:
            if self._detector is None:
                detector = self._detector_factory()
                try:
                    detector.load()
                except Exception as exc:
                    raise DetectorUnavailable(str(exc)) from exc
                self._detector = detector
            return self._detector

    def _ensure_tracker(self) -> Tracker:
        with self._model_lock:
            if self._tracker is None:
                self._tracker = self._tracker_factory()
            return self._tracker

    def _release_models(self) -> None:
        with self._model_lock:
            detector, tracker = self._detector, self._tracker
            self._detector = None
            self._tracker = None
        if detector is not None:
            try:
                detector.close()
            except Exception:  # pragma: no cover
                pass
        if tracker is not None and hasattr(tracker, "reset"):
            try:
                tracker.reset()
            except Exception:  # pragma: no cover
                pass

    # -- run loop ------------------------------------------------------------------
    def _run(self) -> None:
        self._logger.info("camera %s: worker starting", self._camera.id)
        attempt = 0
        try:
            while not self._stop.is_set():
                self._report(CameraStatus.CONNECTING)
                target = self._validate_target()
                if target is None:
                    return
                processed = False
                detail: str | None = None
                source = self._build_source(target)
                self._set_source(source)
                try:
                    seed = self._open_and_prime(source)
                    if seed is not None:
                        try:
                            processed = self._run_session(source, seed)
                        except DetectorUnavailable as exc:
                            self._logger.warning(
                                "camera %s: detector could not be loaded: %s",
                                self._camera.id,
                                exc,
                            )
                            self._terminal(CameraStatus.FAILED, DETAIL_DETECTOR_LOAD_FAILED)
                            return
                        detail = self._last_detail
                    else:
                        detail = self._last_detail or DETAIL_OPEN_FAILED
                finally:
                    self._close_source()
                if self._stop.is_set():
                    break
                fallback = DETAIL_READ_FAILED if processed else DETAIL_OPEN_FAILED
                self._report(CameraStatus.DISCONNECTED, detail or fallback)

                next_attempt = attempt + 1
                if (
                    self._settings.reconnect_max_attempts
                    and next_attempt >= self._settings.reconnect_max_attempts
                ):
                    self._logger.warning(
                        "camera %s: giving up after %d attempts", self._camera.id, next_attempt
                    )
                    self._terminal(CameraStatus.FAILED, DETAIL_RECONNECT_EXHAUSTED)
                    return
                self._report(CameraStatus.RECONNECTING, DETAIL_BACKOFF)
                if not self._backoff(attempt):
                    break
                attempt = next_attempt

            self._report(CameraStatus.STOPPED, DETAIL_REQUESTED)
        except Exception:  # never let a worker crash the process (FR-06 groundwork)
            self._logger.exception("camera %s: unexpected worker failure", self._camera.id)
            self._report(CameraStatus.FAILED, "worker_error")
        finally:
            self._queue.close()
            self._release_models()
            self._logger.info("camera %s: worker stopped", self._camera.id)

    def _validate_target(self) -> PinnedTarget | None:
        try:
            return resolve_and_validate(
                self._camera.stream_reference,
                allowed_schemes=self._settings.allowed_stream_schemes,
                allow_private=self._settings.allow_private_networks,
                host_mode=self._settings.stream_host_mode,
            )
        except StreamSecurityError as exc:
            # Non-recoverable: the target is unsafe or unresolvable.
            self._logger.warning(
                "camera %s: stream rejected at connect time (%s)", self._camera.id, exc.reason
            )
            self._terminal(CameraStatus.FAILED, exc.reason)
            return None
        except Exception:
            self._logger.exception("camera %s: target validation failed", self._camera.id)
            self._terminal(CameraStatus.FAILED, DETAIL_INSECURE_TARGET)
            return None

    def _open_and_prime(self, source: FrameSource) -> RawFrame | None:
        self._metrics.record_connect_attempt()
        try:
            opened = source.open()
        except Exception:
            opened = False
        if not opened:
            self._metrics.record_connect_failure()
            self._last_detail = DETAIL_OPEN_FAILED
            self._logger.warning("camera %s: could not open stream", self._camera.id)
            return None
        try:
            raw = source.read()
        except Exception:
            raw = None
        if raw is None or not is_valid_frame(raw.image):
            self._metrics.record_connect_failure()
            if raw is None:
                self._metrics.record_decode_error()
            self._last_detail = DETAIL_READ_FAILED
            return None
        return raw

    def _run_session(self, source: FrameSource, seed: RawFrame) -> bool:
        detector = self._ensure_detector()
        tracker = self._ensure_tracker()
        tracker.reset()  # FR-08: never carry tracks across a connection gap
        if self._engine is not None:
            self._engine.reset()  # FR-08: no event is inferred across a stream gap
        if self._evidence is not None:
            # Finalise open captures against the old buffer before it is cleared.
            self._evidence.reset()
        self._buffer.clear()
        self._sampling.reset()
        self._session_start = self._clock()
        self._capture_done = False
        self._capture_error = None
        self._last_detail = None
        self._degrade_processed = 0
        self._degrade_received = 0
        self._degrade_dropped = 0

        capture = threading.Thread(
            target=self._capture_loop,
            args=(source, seed),
            name=f"cv-camera-{self._camera.id}-capture",
            daemon=True,
        )
        self._capture_thread = capture
        capture.start()
        try:
            return self._process_loop(source, detector, tracker)
        finally:
            self._finalise_events()
            self._close_source()
            capture.join(timeout=self._settings.connect_timeout_seconds)
            self._capture_thread = None

    def _capture_loop(self, source: FrameSource, seed: RawFrame) -> None:
        try:
            self._enqueue(seed)
            while not self._stop.is_set():
                raw = source.read()
                if raw is None:
                    self._capture_error = DETAIL_READ_FAILED
                    self._metrics.record_decode_error()
                    return
                self._metrics.record_received()
                if not self._sampling.should_process(self._clock()):
                    self._metrics.record_skipped()
                    continue
                self._enqueue(raw)
        except Exception:
            self._capture_error = DETAIL_READ_FAILED
            self._logger.warning("camera %s: capture error", self._camera.id, exc_info=True)
        finally:
            self._capture_done = True
            self._queue.wake()

    def _enqueue(self, raw: RawFrame) -> None:
        frame = tag_frame(self._camera.id, raw, clock=self._clock)
        self._queue.put(frame)

    def _process_loop(self, source: FrameSource, detector: Detector, tracker: Tracker) -> bool:
        processed_any = False
        while not self._stop.is_set():
            self._maybe_heartbeat()
            item = self._queue.get(timeout=0.25)
            now = self._clock()
            if item is None:
                if self._capture_done:
                    self._last_detail = self._capture_error or DETAIL_READ_FAILED
                    return processed_any
                reference = source.last_frame_monotonic
                if reference is None:
                    reference = self._session_start
                if now - reference > self._settings.read_timeout_seconds:
                    self._last_detail = DETAIL_STREAM_STALLED
                    return processed_any
                continue
            if not isinstance(item, Frame) or not is_valid_frame(item.image):
                self._metrics.record_invalid()
                continue
            try:
                prepared = prepare_frame(item.image, width=self._settings.process_width)
                # The detector is trained on upright people: feed it a rotated frame for
                # cameras that publish a sideways picture, then map boxes back so zones,
                # boundaries and every rule keep operating in the original frame (D-72).
                detection_input = (
                    rotate_frame(prepared, self._rotation) if self._rotation else prepared
                )
                detections: list[Detection] = detector.detect(detection_input)
                if self._rotation:
                    height, width = int(prepared.shape[0]), int(prepared.shape[1])
                    detections = [
                        replace(
                            detection,
                            bbox=map_bbox_from_rotated(
                                detection.bbox, self._rotation, width, height
                            ),
                        )
                        for detection in detections
                    ]
                tracks = tracker.update(detections)
            except Exception:
                self._metrics.record_processing_error()
                self._logger.warning("camera %s: processing error", self._camera.id, exc_info=True)
                continue
            self._metrics.record_processing(now, self._clock())
            self._observe_events(prepared, tracks, now)
            observation = FrameObservation(
                camera_id=self._camera.id,
                position_seconds=item.position_seconds,
                arrival_utc=item.arrival_utc,
                image=item.image,
                tracks=tracks,
                monotonic=now,
            )
            self._buffer.append(observation)
            if self._evidence is not None:
                # Non-blocking: this only records the frame in open capture windows.
                self._evidence.on_frame(observation, now)
            processed_any = True
            if self._state in (CameraStatus.CONNECTING, CameraStatus.RECONNECTING):
                self._report(CameraStatus.ACTIVE)
            self._evaluate_degraded()
        return processed_any

    # -- temporal events -----------------------------------------------------------
    def _observe_events(self, image: Any, tracks: list[Track], monotonic: float) -> None:
        """Feed one processed frame to the event engine (never blocks the loop)."""
        engine = self._engine
        if engine is None:
            return
        shape = getattr(image, "shape", None)
        if shape is None or len(shape) < 2:
            return
        height, width = int(shape[0]), int(shape[1])
        if width < 1 or height < 1:
            return
        frame = EngineFrame(
            camera_id=self._camera.id,
            monotonic=monotonic,
            observed_at=self._wall_clock(),
            frame_width=width,
            frame_height=height,
            tracks=[
                EntityObservation(
                    track_id=track.track_id,
                    class_name=track.class_name,
                    confidence=track.confidence,
                    bbox=track.bbox,
                )
                for track in tracks
            ],
        )
        try:
            transitions = engine.observe(frame)
        except Exception:
            with self._event_lock:
                self._event_errors += 1
            self._logger.warning(
                "camera %s: event engine failed on a frame", self._camera.id, exc_info=True
            )
            return
        with self._event_lock:
            self._events_emitted += len(transitions)

    def _finalise_events(self) -> None:
        """Mark persistent events incomplete and close open captures at stream end."""
        now = self._clock()
        engine = self._engine
        if engine is not None:
            try:
                transitions = engine.on_stream_end(
                    monotonic=now,
                    observed_at=self._wall_clock(),
                    reason="stream_ended",
                )
            except Exception:
                with self._event_lock:
                    self._event_errors += 1
                self._logger.warning(
                    "camera %s: event finalisation failed", self._camera.id, exc_info=True
                )
            else:
                with self._event_lock:
                    self._events_emitted += len(transitions)
        if self._evidence is not None:
            # Finalise captures opened by the transitions published just above.
            self._evidence.on_stream_end(now)

    def _evaluate_degraded(self) -> None:
        processed = self._metrics.processed_count()
        if processed - self._degrade_processed < self._settings.degraded_window_frames:
            return
        snapshot = self._metrics.snapshot()
        received = int(snapshot["frames_received"])
        skipped = int(snapshot["frames_skipped"])
        dropped = self._queue.dropped
        enqueued = (received - skipped) - (self._degrade_received)
        dropped_delta = dropped - self._degrade_dropped
        self._degrade_processed = processed
        self._degrade_received = received - skipped
        self._degrade_dropped = dropped
        if enqueued <= 0:
            return
        if (dropped_delta / enqueued) >= self._settings.degraded_drop_ratio:
            self._report(CameraStatus.DEGRADED, "backpressure")
        else:
            self._report(CameraStatus.ACTIVE)

    def _backoff(self, attempt: int) -> bool:
        delay = min(
            self._settings.reconnect_initial_backoff_seconds * (2**attempt),
            self._settings.reconnect_max_backoff_seconds,
        )
        return self._interruptible_sleep(delay)

    def _interruptible_sleep(self, seconds: float) -> bool:
        remaining = max(0.0, seconds)
        while remaining > 0 and not self._stop.is_set():
            step = min(remaining, 0.25)
            if self._stop.wait(step):
                return False
            remaining -= step
            self._maybe_heartbeat()
        return not self._stop.is_set()
