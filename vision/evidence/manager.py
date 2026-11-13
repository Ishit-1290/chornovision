"""Event-linked evidence capture (Phase 6; FR-36, FR-37).

The manager is fed the same processed frames as the detector/event engine, so it can retain
the pre-event window from a bounded rolling buffer and keep collecting during the post-event
window. It never encodes on the caller's thread: a finalized capture is queued to a dedicated
encoder thread, which writes the snapshot/clip and hands the metadata to the backend.

Bounded by construction:

* the pre-event frames come from the worker's bounded rolling buffer;
* each clip retains at most ``clip_max_frames`` frames;
* at most ``max_active_events`` captures are tracked at once (the oldest is finalized early);
* the encoder queue is bounded, and overflow is reported as an explicit capture failure rather
  than silently dropped or allowed to grow without limit.
"""

from __future__ import annotations

import logging
import queue
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.events.types import EventTransition

from vision.evidence.store import EvidenceRecord, EvidenceStore
from vision.ingestion.rotation import normalize_rotation, rotate_frame

LOGGER = logging.getLogger("vision.evidence.manager")


class BufferedFrame(Protocol):
    """The subset of a buffered observation the manager needs."""

    monotonic: float
    image: Any
    arrival_utc: datetime


class BufferLike(Protocol):
    def snapshot(self) -> list[Any]: ...


@dataclass(frozen=True)
class EvidencePolicy:
    """Configurable capture window and bounds (defaults from D-11)."""

    enabled: bool = True
    pre_event_seconds: float = 5.0
    post_event_seconds: float = 5.0
    snapshot_enabled: bool = True
    clip_fps: float = 5.0
    clip_max_frames: int = 150
    max_active_events: int = 32
    max_seen_events: int = 2048

    @classmethod
    def from_settings(cls, settings: Any) -> EvidencePolicy:
        return cls(
            enabled=bool(settings.evidence_enabled),
            pre_event_seconds=max(0.0, float(settings.evidence_pre_event_seconds)),
            post_event_seconds=max(0.0, float(settings.evidence_post_event_seconds)),
            snapshot_enabled=bool(settings.evidence_snapshot_enabled),
            clip_fps=max(0.001, float(settings.evidence_clip_fps)),
            clip_max_frames=max(1, int(settings.evidence_clip_max_frames)),
        )


@dataclass
class _Collection:
    event_id: str
    camera_id: int
    captured_at: datetime
    trigger_monotonic: float
    deadline: float
    pre_frames: list[Any] = field(default_factory=list)
    post_frames: list[Any] = field(default_factory=list)
    snapshot_image: Any | None = None


@dataclass
class _EncodeJob:
    event_id: str
    camera_id: int
    captured_at: datetime
    frame_images: list[Any]
    snapshot_image: Any | None


Registrar = Callable[[EvidenceRecord], None]


class EvidenceManager:
    """Turns event transitions into snapshot/clip evidence, off the frame loop."""

    def __init__(
        self,
        *,
        policy: EvidencePolicy,
        store: EvidenceStore,
        registrar: Registrar,
        encoder_queue_maxsize: int = 16,
        rotation: int = 0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._policy = policy
        self._store = store
        self._registrar = registrar
        #: Detection-time rotation for this camera (D-72/D-74). Evidence is written in the
        #: camera's straightened orientation so recorded snapshots/clips match the live
        #: view instead of staying sideways; ``0`` leaves the bytes untouched.
        self._rotation = normalize_rotation(rotation)
        self._logger = logger or LOGGER
        self._buffer: BufferLike | None = None
        self._active: dict[str, _Collection] = {}
        self._seen: set[str] = set()
        self._seen_order: deque[str] = deque(maxlen=policy.max_seen_events)
        self._jobs: queue.Queue[_EncodeJob] = queue.Queue(maxsize=encoder_queue_maxsize)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()
        self._lock = threading.Lock()
        self._counters = {
            "capture_started": 0,
            "evidence_registered": 0,
            "evidence_failed": 0,
            "dropped_collections": 0,
            "dropped_jobs": 0,
        }

    # -- lifecycle -----------------------------------------------------------------
    def bind_buffer(self, buffer: BufferLike) -> None:
        self._buffer = buffer

    def start(self) -> None:
        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._encode_loop, name="cv-evidence-encoder", daemon=True
            )
            self._thread.start()

    def shutdown(self, timeout: float = 5.0) -> None:
        with self._lock:
            pending = list(self._active.values())
            self._active.clear()
        for collection in pending:
            self._finalise(collection)
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    # -- input ---------------------------------------------------------------------
    def handle_transition(self, transition: EventTransition, monotonic: float) -> None:
        """Begin (or ignore a duplicate) capture for one event transition."""
        if not self._policy.enabled:
            return
        snapshot = transition.event
        with self._lock:
            if not self._mark_seen(snapshot.event_id):
                return
            if len(self._active) >= self._policy.max_active_events:
                oldest_id = next(iter(self._active))
                oldest = self._active.pop(oldest_id)
                self._counters["dropped_collections"] += 1
                self._logger.warning(
                    "evidence: too many active captures; finalising %s early", oldest_id
                )
                self._finalise_locked(oldest)
            collection = _Collection(
                event_id=snapshot.event_id,
                camera_id=snapshot.camera_id,
                captured_at=snapshot.trigger_time,
                trigger_monotonic=monotonic,
                deadline=monotonic + self._policy.post_event_seconds,
                pre_frames=self._pre_frames(monotonic),
            )
            self._counters["capture_started"] += 1
            if self._policy.post_event_seconds <= 0:
                self._finalise_locked(collection)
            else:
                self._active[snapshot.event_id] = collection

    def on_frame(self, frame: BufferedFrame, monotonic: float) -> None:
        """Record a processed frame for every active capture (worker thread, non-blocking)."""
        if not self._active:
            return
        finalise: list[_Collection] = []
        with self._lock:
            for collection in self._active.values():
                if collection.snapshot_image is None:
                    collection.snapshot_image = getattr(frame, "image", None)
                budget = self._policy.clip_max_frames - len(collection.pre_frames)
                if budget > 0 and len(collection.post_frames) < budget:
                    collection.post_frames.append(frame)
                if monotonic >= collection.deadline:
                    finalise.append(collection)
            for collection in finalise:
                self._active.pop(collection.event_id, None)
                self._finalise_locked(collection)

    def on_stream_end(self, monotonic: float) -> None:
        """Finalise every active capture when the stream/session ends."""
        with self._lock:
            pending = list(self._active.values())
            self._active.clear()
            for collection in pending:
                self._finalise_locked(collection)

    def reset(self) -> None:
        """Finalise active captures before a reconnect clears the frame buffer (FR-08)."""
        self.on_stream_end(0.0)

    # -- internals -----------------------------------------------------------------
    def _mark_seen(self, event_id: str) -> bool:
        if event_id in self._seen:
            return False
        if len(self._seen_order) == self._seen_order.maxlen and self._seen_order:
            self._seen.discard(self._seen_order[0])
        self._seen_order.append(event_id)
        self._seen.add(event_id)
        return True

    def _pre_frames(self, monotonic: float) -> list[Any]:
        buffer = self._buffer
        if buffer is None:
            return []
        cutoff = monotonic - self._policy.pre_event_seconds
        frames = [
            frame
            for frame in buffer.snapshot()
            if float(getattr(frame, "monotonic", -1.0)) >= cutoff
        ]
        if len(frames) > self._policy.clip_max_frames:
            frames = frames[-self._policy.clip_max_frames :]
        return frames

    def _finalise_locked(self, collection: _Collection) -> None:
        images = [
            getattr(frame, "image", None)
            for frame in (*collection.pre_frames, *collection.post_frames)
            if getattr(frame, "image", None) is not None
        ]
        if len(images) > self._policy.clip_max_frames:
            images = images[-self._policy.clip_max_frames :]
        snapshot_image = collection.snapshot_image
        if snapshot_image is None and images:
            snapshot_image = images[-1]
        job = _EncodeJob(
            event_id=collection.event_id,
            camera_id=collection.camera_id,
            captured_at=collection.captured_at,
            frame_images=images,
            snapshot_image=snapshot_image,
        )
        self._enqueue_locked(job)

    def _finalise(self, collection: _Collection) -> None:
        with self._lock:
            self._finalise_locked(collection)

    def _enqueue_locked(self, job: _EncodeJob) -> None:
        try:
            self._jobs.put_nowait(job)
            self.start()
        except queue.Full:
            self._counters["dropped_jobs"] += 1
            self._logger.warning(
                "evidence: encoder queue full; recording capture failure for %s", job.event_id
            )
            self._emit_failed(job, "encoder_overloaded")

    def _emit_failed(self, job: _EncodeJob, error: str) -> None:
        if self._policy.snapshot_enabled:
            self._register(self._failed(job, "snapshot", error))
        self._register(self._failed(job, "clip", error))
        self._counters["evidence_failed"] += 1

    def _failed(self, job: _EncodeJob, media_type: str, error: str) -> EvidenceRecord:
        return EvidenceRecord(
            event_id=job.event_id,
            media_type=media_type,
            status="failed",
            relative_path=None,
            file_size_bytes=None,
            duration_seconds=None,
            captured_at=job.captured_at,
            error=error,
        )

    def _register(self, record: EvidenceRecord) -> None:
        try:
            self._registrar(record)
        except Exception:  # pragma: no cover - the handoff enqueue must not raise
            self._logger.warning("evidence: could not hand off %s", record.event_id, exc_info=True)
            return
        if record.status == "available":
            self._counters["evidence_registered"] += 1
        else:
            self._counters["evidence_failed"] += 1

    def _encode_loop(self) -> None:
        while True:
            try:
                job = self._jobs.get(timeout=0.1)
            except queue.Empty:
                if self._stop.is_set():
                    return
                continue
            try:
                self._encode(job)
            except Exception:  # pragma: no cover - defensive
                self._logger.warning("evidence: unexpected encode error", exc_info=True)
            finally:
                self._jobs.task_done()
            if self._stop.is_set() and self._jobs.empty():
                return

    def _encode(self, job: _EncodeJob) -> None:
        if self._policy.snapshot_enabled:
            if job.snapshot_image is None:
                # Never claim a snapshot; record the failure explicitly (FR-39).
                self._register(self._failed(job, "snapshot", "no_frames"))
            else:
                self._register(self._save_snapshot(job))
        if job.frame_images:
            self._register(self._save_clip(job))
        else:
            # No footage survived the window: never report an empty clip as available.
            self._register(self._failed(job, "clip", "no_frames"))

    def _save_snapshot(self, job: _EncodeJob) -> EvidenceRecord:
        # Rotate on the encoder thread (never the frame loop) so the stored snapshot is
        # upright for a sideways camera; ``0`` is a passthrough (D-72/D-73).
        image = rotate_frame(job.snapshot_image, self._rotation)
        try:
            return self._store.save_snapshot(
                camera_id=job.camera_id,
                event_id=job.event_id,
                captured_at=job.captured_at,
                image=image,
            )
        except Exception:  # pragma: no cover - store normally converts failures
            self._logger.warning("evidence: snapshot error for %s", job.event_id, exc_info=True)
            return self._failed(job, "snapshot", "encode_error")

    def _save_clip(self, job: _EncodeJob) -> EvidenceRecord:
        # Rotate every retained frame once, on the encoder thread, so the clip plays in the
        # same orientation as the live view; ``0`` is a passthrough (D-72/D-73).
        frames = [rotate_frame(frame, self._rotation) for frame in job.frame_images]
        try:
            return self._store.save_clip(
                camera_id=job.camera_id,
                event_id=job.event_id,
                captured_at=job.captured_at,
                frames=frames,
                fps=self._policy.clip_fps,
            )
        except Exception:  # pragma: no cover - store normally converts failures
            self._logger.warning("evidence: clip error for %s", job.event_id, exc_info=True)
            return self._failed(job, "clip", "encode_error")

    # -- introspection -------------------------------------------------------------
    def counters(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)

    @property
    def active_captures(self) -> int:
        with self._lock:
            return len(self._active)
