"""Bounded worker→backend event handoff with a best-effort disk spool (OQ-09/D-12, FR-40).

The event engine publishes on the frame-processing thread, so publishing must never block:
this module enqueues into a bounded in-memory queue and a single background thread performs
the authenticated HTTP delivery. Delivery semantics:

* **at-least-once + idempotent** — duplicate/re-ordered submissions are no-ops on the
  backend because of ``event_id``/``state_version`` (D-12);
* **transient failures** (network, 5xx, 408/429, or evidence arriving before its event) are
  retried with capped backoff up to ``max_attempts``;
* **permanent failures** (422/404 on an event) are recorded and discarded, never retried;
* **overflow** spills to a bounded on-disk spool instead of dropping silently; only when the
  spool itself is full is an item counted as dropped, and that is logged explicitly.

Per-camera isolation (Phase 8): each handoff owns only the spool files it wrote
(``handoff-<camera_id>-*.json``). In a multi-camera worker process the spool directory is
shared, but a camera's deliverer never reads or delivers another camera's spooled items, and
the ``spool_max_bytes`` bound is applied **per camera** so one camera's backlog cannot evict
another's. A restarted worker recovers only its own camera's spool. The spool is
best-effort rather than a write-ahead log: an item's file is removed before its delivery
attempt, so a crash at exactly that moment can lose it (delivery is at-least-once only
while the process is alive).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.events.types import EventTransition

from vision.evidence.store import EvidenceRecord
from vision.internal_client import (
    InternalClient,
    InternalClientError,
    PermanentInternalError,
)

LOGGER = logging.getLogger("vision.event_handoff")


@dataclass
class _Item:
    kind: str  # "event" | "evidence"
    payload: dict[str, Any]
    attempts: int = 0


@dataclass
class _Counters:
    enqueued: int = 0
    delivered: int = 0
    spooled: int = 0
    dropped: int = 0
    failed: int = 0


def _encode_evidence(record: EvidenceRecord) -> dict[str, Any]:
    return {
        "event_id": record.event_id,
        "media_type": record.media_type,
        "status": record.status,
        "relative_path": record.relative_path,
        "file_size_bytes": record.file_size_bytes,
        "duration_seconds": record.duration_seconds,
        "captured_at": record.captured_at.isoformat(),
        "error": record.error,
    }


@dataclass
class EventHandoff:
    """Non-blocking event/evidence submission with a bounded background deliverer."""

    client: InternalClient
    camera_id: int
    queue_maxsize: int = 1000
    spool_dir: Path | None = None
    spool_max_bytes: int = 5_000_000
    max_attempts: int = 5
    retry_backoff_seconds: float = 0.5
    logger: logging.Logger | None = None

    def __post_init__(self) -> None:
        self._logger = self.logger or LOGGER
        self._queue: deque[_Item] = deque()
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()
        self._counters = _Counters()
        self._spool_dir = self.spool_dir
        self._spool_bytes = self._spool_count = 0
        self._spool_seq = 0
        self._spool_scanned = False
        self._inflight = 0

    # -- lifecycle -----------------------------------------------------------------
    def start(self) -> None:
        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run, name=f"cv-handoff-{self.camera_id}", daemon=True
            )
            self._thread.start()

    def shutdown(self, timeout: float = 5.0) -> None:
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None
        self._spill_remaining()

    def flush(self, timeout: float = 5.0) -> bool:
        """Wait until the in-memory queue and spool are empty (used by tests/shutdown)."""
        deadline = time.monotonic() + timeout
        with self._condition:
            while self._queue or self._spool_count or self._inflight:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._condition.wait(min(0.05, remaining))
        return True

    # -- input ---------------------------------------------------------------------
    def enqueue_event(self, transition: EventTransition) -> None:
        payload = {
            "action": transition.action.value,
            "event": transition.event.model_dump(mode="json"),
        }
        self._enqueue(_Item(kind="event", payload=payload))

    def enqueue_evidence(self, record: EvidenceRecord) -> None:
        self._enqueue(_Item(kind="evidence", payload=_encode_evidence(record)))

    def _enqueue(self, item: _Item) -> None:
        self.start()
        with self._condition:
            if len(self._queue) < self.queue_maxsize:
                self._queue.append(item)
                self._counters.enqueued += 1
                self._condition.notify()
                return
        # Queue full: spill to disk outside the lock so the producer never blocks on I/O.
        self._spool(item)

    # -- delivery ------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop.is_set():
            item = self._next_item()
            if item is None:
                with self._condition:
                    # Re-check under the lock: an item enqueued between the empty check and
                    # the wait would otherwise be missed and delayed by the whole poll
                    # interval (a lost wakeup).
                    if not self._queue:
                        self._condition.wait(0.1)
                continue
            try:
                try:
                    self._deliver(item)
                except PermanentInternalError as exc:
                    self._counters.failed += 1
                    self._logger.warning(
                        "handoff: discarding unrecoverable %s for camera %s: %s",
                        item.kind,
                        self.camera_id,
                        exc,
                    )
                    continue
                except InternalClientError as exc:
                    item.attempts += 1
                    if item.attempts >= self.max_attempts:
                        self._counters.failed += 1
                        self._logger.warning(
                            "handoff: giving up on %s after %d attempts: %s",
                            item.kind,
                            item.attempts,
                            exc,
                        )
                        continue
                    self._requeue_front(item)
                    self._stop.wait(min(self.retry_backoff_seconds * item.attempts, 5.0))
                    continue
                self._counters.delivered += 1
            finally:
                self._finish_item()

    def _deliver(self, item: _Item) -> None:
        if item.kind == "event":
            self.client.submit_event(item.payload)
        elif item.kind == "evidence":
            self.client.register_evidence(item.payload["event_id"], item.payload)
        else:  # pragma: no cover - defensive
            raise PermanentInternalError(f"unknown handoff kind {item.kind!r}")

    def _next_item(self) -> _Item | None:
        with self._condition:
            if self._queue:
                item = self._queue.popleft()
                self._inflight += 1
                return item
        item = self._read_spool()
        if item is not None:
            with self._condition:
                self._inflight += 1
        return item

    def _finish_item(self) -> None:
        with self._condition:
            self._inflight = max(0, self._inflight - 1)
            self._condition.notify_all()

    def _requeue_front(self, item: _Item) -> None:
        with self._condition:
            self._queue.appendleft(item)
            self._condition.notify()

    # -- spool ---------------------------------------------------------------------
    def _path(self) -> Path:
        base = self._spool_dir
        if base is None:
            from app.config import get_settings

            base = Path(get_settings().evidence_dir).expanduser().parent / "spool"
        return Path(base)

    def _scan_spool(self) -> None:
        if self._spool_scanned:
            return
        self._spool_scanned = True
        directory = self._path()
        if not directory.is_dir():
            return
        total = 0
        count = 0
        for path in directory.glob(f"handoff-{self.camera_id}-*.json"):
            try:
                total += path.stat().st_size
                count += 1
            except OSError:  # pragma: no cover
                continue
        self._spool_bytes = total
        self._spool_count = count

    def _spool(self, item: _Item) -> None:
        self._scan_spool()
        data = json.dumps({"kind": item.kind, "payload": item.payload}).encode("utf-8")
        with self._lock:
            if self._spool_bytes + len(data) > self.spool_max_bytes:
                self._counters.dropped += 1
                self._logger.error(
                    "handoff: spool full; dropped one %s for camera %s",
                    item.kind,
                    self.camera_id,
                )
                return
            self._spool_seq += 1
            seq = self._spool_seq
        directory = self._path()
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / f"handoff-{self.camera_id}-{time.time_ns()}-{seq}.json"
            path.write_bytes(data)
        except OSError:
            with self._lock:
                self._counters.dropped += 1
            self._logger.error("handoff: could not write spool file", exc_info=True)
            return
        with self._condition:
            self._spool_bytes += len(data)
            self._spool_count += 1
            self._counters.spooled += 1
            self._condition.notify_all()

    def _spool_files(self) -> list[Path]:
        directory = self._path()
        if not directory.is_dir():
            return []
        # Per-camera isolation: only this camera's spool files are read/delivered.
        return sorted(directory.glob(f"handoff-{self.camera_id}-*.json"))

    def _read_spool(self) -> _Item | None:
        for path in self._spool_files():
            try:
                raw = path.read_bytes()
            except OSError:  # pragma: no cover
                continue
            try:
                data = json.loads(raw.decode("utf-8"))
                item = _Item(kind=str(data["kind"]), payload=dict(data["payload"]))
            except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                self._discard_spool_file(path, len(raw))
                self._counters.failed += 1
                continue
            self._discard_spool_file(path, len(raw))
            return item
        return None

    def _discard_spool_file(self, path: Path, size: int) -> None:
        try:
            path.unlink()
        except OSError:  # pragma: no cover
            return
        with self._condition:
            self._spool_bytes = max(0, self._spool_bytes - size)
            self._spool_count = max(0, self._spool_count - 1)
            self._condition.notify_all()

    def _spill_remaining(self) -> None:
        with self._condition:
            remaining = list(self._queue)
            self._queue.clear()
        for item in remaining:
            self._spool(item)

    # -- introspection -------------------------------------------------------------
    def counters(self) -> dict[str, int]:
        with self._lock:
            return {
                "enqueued": self._counters.enqueued,
                "delivered": self._counters.delivered,
                "spooled": self._counters.spooled,
                "dropped": self._counters.dropped,
                "failed": self._counters.failed,
            }
