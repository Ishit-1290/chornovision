"""Benchmark-harness tests (Phase 8; NFR-13, NFR-15).

These verify the harness is correct and reproducible in *shape*: the helpers behave, the
deterministic micro-benchmarks return percentiles, and a short real-decode camera run produces
the expected measured fields. They deliberately assert structure and non-degeneracy rather than
timing values, which are machine-dependent. OpenCV-dependent tests skip when it is unavailable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vision.benchmarks.harness import (
    BenchmarkConfig,
    LoopingClipSource,
    SyntheticDetector,
    build_clip,
    cpu_seconds,
    environment_info,
    gpu_info,
    measure_event_handoff_latency,
    measure_evidence_encode_latency,
    measure_recovery_time,
    percentiles_ms,
    read_rss_mb,
    run_camera_benchmark,
    write_report,
)


def test_percentiles_are_nearest_rank() -> None:
    assert percentiles_ms([])["p50_ms"] is None
    result = percentiles_ms([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    assert result["count"] == 10
    # Nearest-rank: p50 -> index ceil(0.5*10)-1 = 4 -> 5.0
    assert result["p50_ms"] == 5.0
    assert result["p95_ms"] == 10.0
    assert result["min_ms"] == 1.0
    assert result["max_ms"] == 10.0


def test_resource_helpers_return_sane_values() -> None:
    rss = read_rss_mb()
    assert rss is None or rss > 0
    assert cpu_seconds() >= 0.0
    info = environment_info()
    assert info["cpu_count"] and info["cpu_count"] >= 1
    assert "python" in info
    # GPU availability is always reported explicitly (available or unavailable + reason).
    gpu = info["gpu"]
    assert isinstance(gpu["available"], bool)
    assert gpu["available"] or gpu["reason"]


def test_gpu_info_reports_availability_explicitly() -> None:
    gpu = gpu_info()
    assert isinstance(gpu["available"], bool)
    if gpu["available"]:
        assert gpu["device"]
    else:
        assert gpu["reason"]


def test_synthetic_detector_reports_cost_and_detections() -> None:
    from vision.detection.detector import Detection

    detection = Detection(class_id=0, class_name="person", confidence=0.9, bbox=(1, 2, 3, 4))
    detector = SyntheticDetector(cost_seconds=0.01, detections=[detection])
    detector.load()
    assert detector.loaded is True
    assert detector.detect(object()) == [detection]


def test_event_handoff_latency_micro_benchmark(tmp_path: Path) -> None:
    result = measure_event_handoff_latency(count=100, spool_dir=tmp_path / "spool")
    assert result["delivered"] == 100
    assert result["dropped"] == 0
    assert result["latency"]["count"] == 100
    assert result["latency"]["p50_ms"] is not None
    assert result["latency"]["p99_ms"] >= result["latency"]["p50_ms"]
    # Delivery is exactly-once: no duplicate publications of the same event id.
    assert result["deliveries_total"] == 100
    assert result["duplicate_deliveries"] == 0
    assert result["duplication_rate"] == 0.0


def test_write_report_is_json_round_trippable(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "report.json"
    write_report(target, {"runs": [{"camera_count": 1}], "micro": {}})
    assert json.loads(target.read_text(encoding="utf-8"))["runs"][0]["camera_count"] == 1


# --- OpenCV-dependent -----------------------------------------------------------


def test_looping_clip_source_wraps_at_end_of_clip(tmp_path: Path) -> None:
    pytest.importorskip("cv2")
    path = build_clip(tmp_path / "clip.avi", frames=5, width=64, height=48, fps=20.0)
    source = LoopingClipSource(path)

    assert source.open() is True
    try:
        # Reading more than the clip length must keep yielding frames (it loops).
        for _ in range(12):
            assert source.read() is not None
    finally:
        source.close()


def test_single_camera_benchmark_produces_measured_fields(tmp_path: Path) -> None:
    pytest.importorskip("cv2")
    config = BenchmarkConfig(
        camera_count=1,
        duration_seconds=1.0,
        process_target_fps=1000.0,
        detector_cost_seconds=0.0,
        clip_frames=30,
        clip_width=64,
        clip_height=48,
        latency_sample_capacity=512,
    )
    result = run_camera_benchmark(config, workdir=tmp_path)

    assert result["camera_count"] == 1
    assert result["wall_seconds"] > 0
    assert result["startup_seconds"] is not None
    camera = result["cameras"][0]
    assert camera["frames_processed"] >= 1
    assert camera["process_fps"] > 0
    assert camera["latency_p50_ms"] is not None
    assert result["totals"]["frames_processed"] >= 1
    assert result["totals"]["process_fps"] > 0
    assert result["detector_mode"] == "synthetic"
    assert isinstance(result["environment"]["gpu"]["available"], bool)
    # The whole report must be JSON-serialisable (it is written to disk by the CLI).
    json.dumps(result)


def test_evidence_encode_latency_micro_benchmark(tmp_path: Path) -> None:
    pytest.importorskip("cv2")
    result = measure_evidence_encode_latency(
        root=tmp_path / "evidence", count=3, width=64, height=48
    )
    assert result["count"] == 3
    assert result["jpeg_bytes"] > 0
    assert result["latency"]["p50_ms"] is not None


def test_recovery_time_micro_benchmark(tmp_path: Path) -> None:
    pytest.importorskip("cv2")
    result = measure_recovery_time(
        workdir=tmp_path,
        outage_seconds=0.3,
        capture_fps=30.0,
        timeout_seconds=10.0,
    )
    assert result["outage_seconds"] == 0.3
    assert result["recovered"] is True
    assert result["recovery_seconds"] is not None
    # Recovery is measured from the outage start, so it cannot be shorter than the outage.
    assert result["recovery_seconds"] >= 0.3
    assert result["reconnect_overhead_seconds"] >= 0.0
