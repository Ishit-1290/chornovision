"""Evaluation tooling tests (Phase 9; G §16.2, W §15).

These tests exercise the *offline* analysis utilities only: matching rules, metric
computation, the dataset loaders, and the command-line runner on the clearly-synthetic
sample dataset. They assert the tooling's arithmetic and documented behaviour; they do
**not** make any claim about real detection accuracy.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.evaluation import (
    ActivityMetrics,
    DetectedEvent,
    LabelledEvent,
    evaluate,
)
from app.evaluation.cli import main, report_to_dict
from app.evaluation.dataset import detected_from_rows, load_detected, load_labels
from app.evaluation.matching import DEFAULT_TOLERANCE_SECONDS, match_activity
from app.evaluation.metrics import OCCUPANCY_EVENT_TYPES

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "evaluation" / "sample"
LABELS_PATH = SAMPLE_DIR / "synthetic_labels.json"
DETECTED_PATH = SAMPLE_DIR / "synthetic_detected.json"


def label(event_type: str, start: int, *, end: int | None = None, camera: int = 1, **kw):
    base = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)
    return LabelledEvent(
        camera_id=camera,
        event_type=event_type,
        start_time=base + timedelta(seconds=start),
        end_time=None if end is None else base + timedelta(seconds=end),
        **kw,
    )


def detected(event_type: str, start: int, *, end: int | None = None, camera: int = 1, **kw):
    base = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)
    return DetectedEvent(
        camera_id=camera,
        event_type=event_type,
        start_time=base + timedelta(seconds=start),
        end_time=None if end is None else base + timedelta(seconds=end),
        **kw,
    )


# --------------------------------------------------------------------------------------
# Matching rules
# --------------------------------------------------------------------------------------


def test_match_within_tolerance_is_true_positive():
    outcome = match_activity([label("person_entering", 0)], [detected("person_entering", 3)])
    assert len(outcome.pairs) == 1
    assert outcome.false_positives == []
    assert outcome.false_negatives == []


def test_match_outside_tolerance_is_fp_and_fn():
    outcome = match_activity([label("person_entering", 0)], [detected("person_entering", 30)])
    assert outcome.pairs == []
    assert len(outcome.false_positives) == 1
    assert len(outcome.false_negatives) == 1


def test_interval_overlap_matches_even_with_distant_starts():
    # Starts are far apart, but the reference interval spans the detection.
    a = label("person_motionless", 0, end=600)
    b = detected("person_motionless", 500, end=520)
    outcome = match_activity([a], [b])
    assert len(outcome.pairs) == 1


def test_matching_is_one_to_one_best_first():
    # Two detections near one label; only the closest may match.
    labels = [label("person_entering", 0)]
    dets = [detected("person_entering", 4), detected("person_entering", 1)]
    outcome = match_activity(labels, dets)
    assert len(outcome.pairs) == 1
    assert outcome.pairs[0].detected.start_time == label("person_entering", 1).start_time
    assert len(outcome.false_positives) == 1


def test_camera_and_type_scope_isolation():
    # Same time, different camera: must not match.
    report = evaluate(
        [label("person_entering", 0, camera=1)],
        [detected("person_entering", 0, camera=2)],
    )
    entering = _row(report, "person_entering")
    assert entering.true_positives == 0
    assert entering.false_positives == 1
    assert entering.false_negatives == 1


def test_tolerance_validation():
    with pytest.raises(ValueError):
        match_activity([], [], tolerance_seconds=-1)


# --------------------------------------------------------------------------------------
# Metric computation
# --------------------------------------------------------------------------------------


def _row(report, event_type: str) -> ActivityMetrics:
    matches = [item for item in report.per_activity if item.event_type == event_type]
    assert matches, f"no metrics row for {event_type}"
    return matches[0]


def test_precision_recall_f1_and_counts():
    labels = [label("person_entering", 0), label("person_entering", 100)]
    dets = [
        detected("person_entering", 0),  # TP
        detected("person_entering", 400),  # FP
    ]
    report = evaluate(labels, dets)
    row = _row(report, "person_entering")
    assert (row.true_positives, row.false_positives, row.false_negatives) == (1, 1, 1)
    assert row.precision == 0.5
    assert row.recall == 0.5
    assert row.f1 == 0.5


def test_timing_error_sign_and_magnitude():
    report = evaluate(
        [label("person_entering", 0, end=10)], [detected("person_entering", 3, end=14)]
    )
    row = _row(report, "person_entering")
    assert row.start_error_mean_seconds == 3.0
    assert row.start_error_median_abs_seconds == 3.0
    assert row.end_error_mean_seconds == 4.0


def test_occupancy_error():
    labels = [label("room_occupancy_change", 0, occupancy=2)]
    dets = [detected("room_occupancy_change", 1, occupancy=3)]
    report = evaluate(labels, dets)
    row = _row(report, "room_occupancy_change")
    assert row.occupancy_error_mean == 1.0
    assert row.occupancy_error_max == 1


def test_undefined_recall_when_no_reference_events():
    report = evaluate([], [detected("person_entering", 0)])
    row = _row(report, "person_entering")
    assert row.recall is None
    assert row.precision == 0.0


def test_micro_macro_and_false_alarm_rate():
    labels = [label("person_entering", 0, end=5), label("person_leaving", 100, end=105)]
    dets = [
        detected("person_entering", 0, end=5),  # TP
        detected("person_leaving", 100, end=105),  # TP
        detected("person_leaving", 300, end=305),  # FP
    ]
    report = evaluate(labels, dets, window_hours=2.0)
    assert report.overall_precision == round(2 / 3, 4)
    assert report.overall_recall == 1.0
    assert report.false_alarms_per_hour == 0.5
    assert report.missed_event_rate == 0.0
    # macro F1 averages each activity's F1: entering 1.0, leaving 0.6667.
    assert report.macro_f1 == 0.8334


def test_missed_event_rate():
    labels = [label("person_entering", 0), label("person_entering", 100)]
    report = evaluate(labels, [])
    assert report.missed_event_rate == 1.0


def test_observed_event_types_fill_zero_rows():
    report = evaluate([], [], observed_event_types=["door_open_too_long"])
    row = _row(report, "door_open_too_long")
    assert row.true_positives == 0
    assert row.precision is None
    assert row.recall is None


def test_occupancy_event_type_set():
    assert OCCUPANCY_EVENT_TYPES == {"room_occupancy_change", "crowd_forming"}


def test_multi_camera_activity_is_merged():
    labels = [label("person_entering", 0, camera=1), label("person_entering", 0, camera=2)]
    dets = [
        detected("person_entering", 0, camera=1),
        detected("person_entering", 0, camera=2),
    ]
    report = evaluate(labels, dets)
    row = _row(report, "person_entering")
    assert row.true_positives == 2
    assert row.precision == 1.0
    assert row.recall == 1.0


# --------------------------------------------------------------------------------------
# Loaders
# --------------------------------------------------------------------------------------


def test_load_labels_and_detected_from_sample():
    labels = load_labels(LABELS_PATH)
    dets = load_detected(DETECTED_PATH)
    assert len(labels) == 8
    assert len(dets) == 9
    assert labels[0].event_type == "person_entering"
    assert labels[3].occupancy == 2
    assert dets[0].event_id == "det-0001"


def test_load_labels_rejects_wrong_shape(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"events": "not-a-list"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_labels(bad)


def test_detected_from_rows_reads_occupancy_attribute():
    rows = [
        {
            "camera_id": 1,
            "event_type": "room_occupancy_change",
            "start_time": "2026-01-01T09:00:00+00:00",
            "end_time": None,
            "event_id": "evt-1",
            "attributes": {"occupancy_count": 4},
        }
    ]
    dets = detected_from_rows(rows)
    assert len(dets) == 1
    assert dets[0].occupancy == 4
    assert dets[0].event_id == "evt-1"


def test_detected_from_rows_supports_objects():
    class Row:
        camera_id = 1
        event_type = "person_entering"
        start_time = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
        end_time = None
        event_id = "evt-obj"
        zone_id = "front_door"
        attributes = {}

    dets = detected_from_rows([Row()])
    assert dets[0].zone_id == "front_door"
    assert dets[0].occupancy is None


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


def test_report_to_dict_is_json_serialisable():
    report = evaluate(load_labels(LABELS_PATH), load_detected(DETECTED_PATH))
    payload = report_to_dict(report)
    text = json.dumps(payload)
    assert "person_entering" in text
    assert isinstance(payload["generated_at"], str)


def test_cli_on_sample_data(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    out = tmp_path / "report.json"
    code = main(
        [
            "--labels",
            str(LABELS_PATH),
            "--detected",
            str(DETECTED_PATH),
            "--output",
            str(out),
            "--window-hours",
            "2",
        ]
    )
    assert code == 0
    captured = capsys.readouterr().out
    assert "person_entering" in captured
    written = json.loads(out.read_text(encoding="utf-8"))
    # The sample is designed with 7 TPs, 2 FPs and 1 FN (see the dataset notes).
    assert written["overall_precision"] == 0.7778
    assert written["overall_recall"] == 0.875
    assert written["overall_f1"] == 0.8235


def test_cli_requires_a_detected_source(capsys: pytest.CaptureFixture[str]):
    code = main(["--labels", str(LABELS_PATH)])
    assert code == 2
    assert "error" in capsys.readouterr().err


def test_cli_rejects_both_sources(capsys: pytest.CaptureFixture[str]):
    code = main(["--labels", str(LABELS_PATH), "--detected", str(DETECTED_PATH), "--from-db"])
    assert code == 2


def test_default_tolerance_value():
    assert DEFAULT_TOLERANCE_SECONDS == 5.0
