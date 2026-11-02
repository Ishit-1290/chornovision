"""Detection-quality metric computation (Phase 9; G §16.2, W §15).

Given reference and detected events, :func:`evaluate` produces per-activity precision,
recall, F1, false-positive/false-negative counts, event-boundary timing error, and occupancy
counting error, plus micro/macro aggregates, false alarms per hour, and the missed-event rate.

All divisions guard against a zero denominator and report ``None`` rather than a fabricated
value (an activity with no reference events has undefined recall).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from app.evaluation.matching import DEFAULT_TOLERANCE_SECONDS, match_activity
from app.evaluation.model import (
    ActivityMetrics,
    DetectedEvent,
    EvaluationReport,
    LabelledEvent,
    MatchOutcome,
)

#: Activities whose count is meaningful for occupancy counting error (G §16.2, W §15).
OCCUPANCY_EVENT_TYPES = frozenset({"room_occupancy_change", "crowd_forming"})


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _f1(precision: float | None, recall: float | None) -> float | None:
    if precision is None or recall is None or (precision + recall) == 0:
        return None
    return round(2 * precision * recall / (precision + recall), 4)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return round(ordered[index], 4)


def _scope_key(event: LabelledEvent | DetectedEvent) -> tuple[int, str]:
    return (event.camera_id, event.event_type)


def _group(events: list) -> dict[tuple[int, str], list]:
    grouped: dict[tuple[int, str], list] = {}
    for event in events:
        grouped.setdefault(_scope_key(event), []).append(event)
    return grouped


def _activity_metrics(event_type: str, outcome: MatchOutcome) -> ActivityMetrics:
    tp = len(outcome.pairs)
    fp = len(outcome.false_positives)
    fn = len(outcome.false_negatives)
    precision = _safe_ratio(tp, tp + fp)
    recall = _safe_ratio(tp, tp + fn)

    start_errors = [pair.start_error_seconds for pair in outcome.pairs]
    start_abs = [abs(value) for value in start_errors]
    end_errors = [
        pair.end_error_seconds for pair in outcome.pairs if pair.end_error_seconds is not None
    ]
    occupancy_errors = [
        pair.occupancy_error for pair in outcome.pairs if pair.occupancy_error is not None
    ]

    return ActivityMetrics(
        event_type=event_type,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1=_f1(precision, recall),
        start_error_mean_seconds=_mean(start_errors),
        start_error_median_abs_seconds=_percentile(start_abs, 0.50),
        start_error_p95_abs_seconds=_percentile(start_abs, 0.95),
        end_error_mean_seconds=_mean([float(value) for value in end_errors]),
        occupancy_error_mean=_mean([float(value) for value in occupancy_errors]),
        occupancy_error_max=(
            max(abs(value) for value in occupancy_errors) if occupancy_errors else None
        ),
    )


def evaluate(
    labels: list[LabelledEvent],
    detected: list[DetectedEvent],
    *,
    tolerance_seconds: float = DEFAULT_TOLERANCE_SECONDS,
    window_hours: float | None = None,
    observed_event_types: list[str] | None = None,
) -> EvaluationReport:
    """Score ``detected`` against ``labels`` and return a full :class:`EvaluationReport`.

    ``window_hours`` (the annotated span, in hours) enables ``false_alarms_per_hour``.
    ``observed_event_types`` lets a caller request zero-metric rows for activities that had no
    reference or detected events, so a complete per-activity table can be reported.
    """
    label_groups = _group(labels)
    detected_groups = _group(detected)

    scopes = set(label_groups) | set(detected_groups)
    # Accumulate raw matches per activity so a multi-camera activity is merged exactly.
    per_type: dict[str, MatchOutcome] = {}
    for _camera_id, event_type in sorted(scopes):
        scope_labels = label_groups.get((_camera_id, event_type), [])
        scope_detected = detected_groups.get((_camera_id, event_type), [])
        outcome = match_activity(scope_labels, scope_detected, tolerance_seconds=tolerance_seconds)
        bucket = per_type.setdefault(event_type, MatchOutcome())
        bucket.pairs.extend(outcome.pairs)
        bucket.false_negatives.extend(outcome.false_negatives)
        bucket.false_positives.extend(outcome.false_positives)

    for event_type in observed_event_types or []:
        per_type.setdefault(event_type, MatchOutcome())

    ordered = [
        _activity_metrics(event_type, per_type[event_type]) for event_type in sorted(per_type)
    ]

    total_tp = sum(item.true_positives for item in ordered)
    total_fp = sum(item.false_positives for item in ordered)
    total_fn = sum(item.false_negatives for item in ordered)
    overall_precision = _safe_ratio(total_tp, total_tp + total_fp)
    overall_recall = _safe_ratio(total_tp, total_tp + total_fn)

    macro_values = [item.f1 for item in ordered if item.f1 is not None]
    macro_f1 = round(sum(macro_values) / len(macro_values), 4) if macro_values else None

    false_alarms_per_hour = (
        round(total_fp / window_hours, 4) if window_hours and window_hours > 0 else None
    )
    missed_event_rate = round(total_fn / len(labels), 4) if labels else None

    return EvaluationReport(
        tolerance_seconds=tolerance_seconds,
        generated_at=datetime.now(UTC),
        total_reference=len(labels),
        total_detected=len(detected),
        per_activity=ordered,
        overall_precision=overall_precision,
        overall_recall=overall_recall,
        overall_f1=_f1(overall_precision, overall_recall),
        macro_f1=macro_f1,
        false_alarms_per_hour=false_alarms_per_hour,
        missed_event_rate=missed_event_rate,
    )
