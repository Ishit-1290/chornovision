"""Thread-safe per-camera stream metrics (NFR-06).

The worker thread writes counters while the supervisor/reporter reads snapshots, so all
access is guarded by a lock. Rates are computed over the worker's lifetime; latency is the
in-process duration from dequeue to completed processing (frame arrival → processing
complete), measured with a monotonic clock (G §14.1). Nothing here is camera-sensitive.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class _Counters:
    received: int = 0
    processed: int = 0
    skipped: int = 0
    invalid: int = 0
    decode_errors: int = 0
    processing_errors: int = 0
    connect_attempts: int = 0
    connect_failures: int = 0
    latency_total: float = 0.0
    latency_max: float = 0.0
    latency_last: float = 0.0


@dataclass
class StreamMetrics:
    """Accumulated metrics for a single camera worker."""

    clock: Callable[[], float] = time.monotonic
    #: Bounded ring of recent frame-processing latencies (seconds) for percentile
    #: reporting. ``0`` disables sampling (default) so the worker keeps a flat profile;
    #: benchmarks enable it to report p50/p95/p99.
    latency_sample_capacity: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    _started: float = field(init=False, default=0.0)
    _counters: _Counters = field(default_factory=_Counters, init=False)
    _latency_samples: deque[float] = field(init=False, default_factory=deque)

    def __post_init__(self) -> None:
        self._started = self._now()
        if self.latency_sample_capacity > 0:
            self._latency_samples = deque(maxlen=int(self.latency_sample_capacity))

    def _now(self) -> float:
        return float(self.clock())

    # -- recording -----------------------------------------------------------------
    def record_connect_attempt(self) -> None:
        with self._lock:
            self._counters.connect_attempts += 1

    def record_connect_failure(self) -> None:
        with self._lock:
            self._counters.connect_failures += 1

    def record_received(self) -> None:
        with self._lock:
            self._counters.received += 1

    def record_skipped(self) -> None:
        with self._lock:
            self._counters.skipped += 1

    def record_invalid(self) -> None:
        with self._lock:
            self._counters.invalid += 1

    def record_decode_error(self) -> None:
        with self._lock:
            self._counters.decode_errors += 1

    def record_processing_error(self) -> None:
        with self._lock:
            self._counters.processing_errors += 1

    def record_processing(self, started: float, finished: float) -> None:
        duration = max(0.0, finished - started)
        with self._lock:
            self._counters.processed += 1
            self._counters.latency_last = duration
            self._counters.latency_total += duration
            if duration > self._counters.latency_max:
                self._counters.latency_max = duration
            if self.latency_sample_capacity > 0:
                self._latency_samples.append(duration)

    def processed_count(self) -> int:
        with self._lock:
            return self._counters.processed

    def _percentiles_locked(self) -> dict[str, float | int | None]:
        """Nearest-rank p50/p95/p99 over the sampled latencies (milliseconds)."""
        samples = sorted(self._latency_samples)
        count = len(samples)

        def rank(fraction: float) -> float | None:
            if not samples:
                return None
            index = max(0, min(count - 1, math.ceil(fraction * count) - 1))
            return round(samples[index] * 1000.0, 3)

        return {
            "latency_sample_count": count,
            "latency_p50_ms": rank(0.50),
            "latency_p95_ms": rank(0.95),
            "latency_p99_ms": rank(0.99),
        }

    # -- reporting -----------------------------------------------------------------
    def snapshot(self) -> dict[str, object]:
        """Return a JSON-serialisable, non-sensitive metrics snapshot."""
        now = self._now()
        with self._lock:
            c = self._counters
            elapsed = max(1e-9, now - self._started)
            processed = c.processed
            avg_ms = (c.latency_total / processed * 1000.0) if processed else 0.0
            snapshot: dict[str, object] = {
                "uptime_seconds": round(elapsed, 3),
                "frames_received": c.received,
                "frames_processed": processed,
                "frames_skipped": c.skipped,
                "frames_invalid": c.invalid,
                "decode_errors": c.decode_errors,
                "processing_errors": c.processing_errors,
                "connect_attempts": c.connect_attempts,
                "connect_failures": c.connect_failures,
                "ingest_fps": round(c.received / elapsed, 3),
                "process_fps": round(processed / elapsed, 3),
                "last_latency_ms": round(c.latency_last * 1000.0, 3),
                "avg_latency_ms": round(avg_ms, 3),
                "max_latency_ms": round(c.latency_max * 1000.0, 3),
            }
            snapshot.update(self._percentiles_locked())
            return snapshot
