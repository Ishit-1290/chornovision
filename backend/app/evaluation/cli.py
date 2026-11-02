"""Command-line evaluation runner (Phase 9; G §16.2, W §15).

Usage::

    python -m app.evaluation --labels evaluation/sample/synthetic_labels.json \\
        --detected evaluation/sample/synthetic_detected.json --output report.json

The detected side can alternatively be read from the configured PostgreSQL database::

    python -m app.evaluation --labels evaluation/sample/synthetic_labels.json --from-db

The command prints a per-activity table and writes a machine-readable JSON report when
``--output`` is given. It never mutates the database (read-only).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.evaluation.dataset import detected_from_rows, load_detected, load_labels
from app.evaluation.metrics import OCCUPANCY_EVENT_TYPES, evaluate
from app.evaluation.model import EvaluationReport

# Every canonical event type, so the per-activity table is complete even when an activity has
# no events in the sample (G §16.2 asks for per-activity reporting).
ALL_ACTIVITIES = [
    "person_entering",
    "person_leaving",
    "room_occupancy_change",
    "crowd_forming",
    "door_open_too_long",
    "package_left_at_entrance",
    "person_motionless",
    "fall_from_bed",
]


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def report_to_dict(report: EvaluationReport) -> dict[str, Any]:
    """Convert a report to a JSON-serialisable dict."""
    return _json_ready(asdict(report))


def _load_from_db() -> list:
    from app.db import dispose_engine, get_session_factory
    from app.repositories import events as events_repo

    db = get_session_factory()()
    try:
        rows = events_repo.list_events(db, limit=10_000, order="asc")
        return detected_from_rows(rows)
    finally:
        db.close()
        dispose_engine()


def _print_table(report: EvaluationReport) -> None:
    header = f"{'activity':<26}{'TP':>4}{'FP':>4}{'FN':>4}{'prec':>8}{'rec':>8}{'F1':>8}"
    print(header)
    print("-" * len(header))
    for item in report.per_activity:

        def fmt(value: float | None) -> str:
            return "-" if value is None else f"{value:.3f}"

        marker = " *" if item.event_type in OCCUPANCY_EVENT_TYPES else ""
        print(
            f"{item.event_type + marker:<26}{item.true_positives:>4}{item.false_positives:>4}"
            f"{item.false_negatives:>4}{fmt(item.precision):>8}{fmt(item.recall):>8}{fmt(item.f1):>8}"
        )
    print("-" * len(header))
    print(
        f"{'overall (micro)':<26}{'':>4}{'':>4}{'':>4}"
        f"{_fmt(report.overall_precision):>8}{_fmt(report.overall_recall):>8}"
        f"{_fmt(report.overall_f1):>8}"
    )
    print(f"macro F1: {_fmt(report.macro_f1)}")
    print(
        f"tolerance: {report.tolerance_seconds}s; reference={report.total_reference}; "
        f"detected={report.total_detected}"
    )
    if report.false_alarms_per_hour is not None:
        print(f"false alarms/hour: {report.false_alarms_per_hour}")
    if report.missed_event_rate is not None:
        print(f"missed-event rate: {report.missed_event_rate}")
    print("(* occupancy activities report counting error in the JSON report)")


def _fmt(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.evaluation")
    parser.add_argument("--labels", required=True, help="reference-event JSON (label format)")
    parser.add_argument("--detected", help="detected-event JSON export")
    parser.add_argument("--from-db", action="store_true", help="read detected events from the DB")
    parser.add_argument("--output", help="write the full JSON report here")
    parser.add_argument("--tolerance-seconds", type=float, default=5.0)
    parser.add_argument("--window-hours", type=float, default=None)
    parser.add_argument(
        "--activities",
        default=",".join(ALL_ACTIVITIES),
        help="comma-separated activities to render (default: all canonical types)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.detected and not args.from_db:
        print("error: provide --detected FILE or --from-db", file=sys.stderr)
        return 2
    if args.detected and args.from_db:
        print("error: --detected and --from-db are mutually exclusive", file=sys.stderr)
        return 2

    labels = load_labels(args.labels)
    detected = _load_from_db() if args.from_db else load_detected(args.detected)
    activities = [item.strip() for item in args.activities.split(",") if item.strip()]

    report = evaluate(
        labels,
        detected,
        tolerance_seconds=args.tolerance_seconds,
        window_hours=args.window_hours,
        observed_event_types=activities,
    )
    _print_table(report)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(report_to_dict(report), indent=2), encoding="utf-8")
        print(f"\nreport written to {args.output}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
