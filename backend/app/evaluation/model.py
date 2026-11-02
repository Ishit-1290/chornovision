"""Input/output shapes for event evaluation (Phase 9; G §16.2).

Two collections are compared:

* :class:`LabelledEvent` — one manually annotated reference event from the labelled set.
* :class:`DetectedEvent` — one event the system actually produced (from a JSON export or the
  ``events`` table).

Both carry a **camera id**, an **event type**, a **start time**, and (where the activity has
a duration) an **end time**. Occupancy activities may also carry an integer ``occupancy``
count so the occupancy counting error can be computed for matched events.

The matching rules that pair them are documented in :mod:`app.evaluation.matching`; the
resulting metrics live in :class:`ActivityMetrics` / :class:`EvaluationReport`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class LabelledEvent:
    """One reference (ground-truth) event from the labelled evaluation set."""

    camera_id: int
    event_type: str
    start_time: datetime
    end_time: datetime | None = None
    zone_id: str | None = None
    #: Occupancy count recorded by the annotator (occupancy activities only).
    occupancy: int | None = None
    #: True when the annotator marked the event ambiguous/uncertain (G §16.2).
    uncertain: bool = False


@dataclass(frozen=True)
class DetectedEvent:
    """One event the system produced (engine output, exported or read from the DB)."""

    camera_id: int
    event_type: str
    start_time: datetime
    end_time: datetime | None = None
    event_id: str | None = None
    zone_id: str | None = None
    occupancy: int | None = None


@dataclass(frozen=True)
class EventPair:
    """A matched (reference, detected) pair plus its measured errors."""

    label: LabelledEvent
    detected: DetectedEvent
    start_error_seconds: float
    end_error_seconds: float | None
    occupancy_error: int | None


@dataclass
class MatchOutcome:
    """The one-to-one matching of two collections for a single activity."""

    pairs: list[EventPair] = field(default_factory=list)
    false_negatives: list[LabelledEvent] = field(default_factory=list)
    false_positives: list[DetectedEvent] = field(default_factory=list)


@dataclass
class ActivityMetrics:
    """Detection-quality metrics for one event type (activity)."""

    event_type: str
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float | None
    recall: float | None
    f1: float | None
    #: Signed mean of ``detected.start - label.start`` over matched pairs (seconds).
    start_error_mean_seconds: float | None
    #: Median absolute start-time error over matched pairs (seconds).
    start_error_median_abs_seconds: float | None
    #: 95th-percentile absolute start-time error over matched pairs (seconds).
    start_error_p95_abs_seconds: float | None
    #: Signed mean end-time error over matched pairs that have both ends (seconds).
    end_error_mean_seconds: float | None
    #: Mean/max absolute occupancy counting error over matched events that carry a count.
    occupancy_error_mean: float | None
    occupancy_error_max: int | None


@dataclass
class EvaluationReport:
    """A full evaluation run: per-activity metrics plus aggregate and provenance fields."""

    tolerance_seconds: float
    generated_at: datetime
    total_reference: int
    total_detected: int
    per_activity: list[ActivityMetrics]
    #: Micro-averaged precision/recall/F1 across every activity.
    overall_precision: float | None
    overall_recall: float | None
    overall_f1: float | None
    #: Macro-averaged F1 over activities that have at least one reference or detection.
    macro_f1: float | None
    #: ``false_positives / window_hours`` when a window is supplied, else ``None``.
    false_alarms_per_hour: float | None
    #: ``false_negatives / total_reference`` (missed-event rate), or ``None`` if no labels.
    missed_event_rate: float | None
    notes: list[str] = field(default_factory=list)
