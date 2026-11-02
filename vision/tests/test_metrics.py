"""Stream-metrics tests (NFR-06, G §14)."""

from __future__ import annotations

from vision.metrics import StreamMetrics

from .fakes import FakeClock


def _metrics() -> tuple[StreamMetrics, FakeClock]:
    clock = FakeClock(1000.0)
    return StreamMetrics(clock=clock), clock


def test_latency_and_processing_counts() -> None:
    metrics, clock = _metrics()
    clock.advance(1.0)
    metrics.record_processing(0.0, 0.05)
    metrics.record_processing(0.0, 0.15)
    snapshot = metrics.snapshot()
    assert metrics.processed_count() == 2
    assert snapshot["frames_processed"] == 2
    assert snapshot["last_latency_ms"] == 150.0
    assert snapshot["max_latency_ms"] == 150.0
    assert snapshot["avg_latency_ms"] == 100.0


def test_rates_are_computed_over_uptime() -> None:
    metrics, clock = _metrics()
    for _ in range(10):
        metrics.record_received()
    for _ in range(4):
        metrics.record_processing(0.0, 0.0)
    clock.advance(2.0)
    snapshot = metrics.snapshot()
    assert snapshot["uptime_seconds"] == 2.0
    assert snapshot["ingest_fps"] == 5.0
    assert snapshot["process_fps"] == 2.0


def test_all_counters_are_reported() -> None:
    metrics, clock = _metrics()
    metrics.record_connect_attempt()
    metrics.record_connect_failure()
    metrics.record_received()
    metrics.record_skipped()
    metrics.record_invalid()
    metrics.record_decode_error()
    metrics.record_processing_error()
    clock.advance(1.0)
    snapshot = metrics.snapshot()
    assert snapshot["connect_attempts"] == 1
    assert snapshot["connect_failures"] == 1
    assert snapshot["frames_received"] == 1
    assert snapshot["frames_skipped"] == 1
    assert snapshot["frames_invalid"] == 1
    assert snapshot["decode_errors"] == 1
    assert snapshot["processing_errors"] == 1


def test_snapshot_is_json_serialisable_when_idle() -> None:
    metrics, _clock = _metrics()
    snapshot = metrics.snapshot()
    assert snapshot["frames_processed"] == 0
    assert snapshot["avg_latency_ms"] == 0.0
    assert snapshot["last_latency_ms"] == 0.0


def test_negative_durations_are_clamped() -> None:
    metrics, _clock = _metrics()
    metrics.record_processing(5.0, 4.0)  # finished before started
    assert metrics.snapshot()["last_latency_ms"] == 0.0


def test_latency_sampling_is_disabled_by_default() -> None:
    metrics, _clock = _metrics()
    for i in range(10):
        metrics.record_processing(0.0, (i + 1) / 1000.0)
    snapshot = metrics.snapshot()
    assert snapshot["latency_sample_count"] == 0
    assert snapshot["latency_p50_ms"] is None


def test_latency_percentiles_are_bounded_and_reported() -> None:
    metrics = StreamMetrics(clock=lambda: 1.0, latency_sample_capacity=4)
    for i in range(10):
        metrics.record_processing(0.0, (i + 1) / 1000.0)  # 1..10 ms, ring keeps last 4
    snapshot = metrics.snapshot()
    assert snapshot["latency_sample_count"] == 4  # bounded ring
    # Last four samples are 7, 8, 9, 10 ms; nearest-rank p50 = index ceil(0.5*4)-1 = 1 -> 8 ms.
    assert snapshot["latency_p50_ms"] == 8.0
    assert snapshot["latency_p95_ms"] == 10.0
    assert snapshot["latency_p99_ms"] == 10.0
