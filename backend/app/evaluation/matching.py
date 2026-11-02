"""Reference↔detection matching rules (Phase 9; G §16.2).

The guidelines require that matching rules are defined **before** metrics are calculated, so
they are fixed and documented here rather than tuned per dataset.

Rules
-----
1. **Scope.** Events are compared only within the same ``(camera_id, event_type)``. A
   detection can never match a reference event of a different activity or a different camera.
2. **Correspondence.** Within a scope, a reference event and a detected event correspond when
   either:
   * their ``[start, end]`` intervals **overlap** (both ends present), or
   * the absolute difference of their **start times** is within ``tolerance_seconds``.
   This tolerates slightly late/early starts and stops while still requiring the two events
   to describe the same occurrence.
3. **One-to-one, best-first.** Candidate pairs are matched greedily by smallest absolute
   start-time difference, so each reference event matches at most one detection and vice
   versa. This avoids double-counting when several detections cluster around one event.
4. **Accounting.** Unmatched reference events are **false negatives** (missed events);
   unmatched detections are **false positives** (false alarms).
5. **Errors.** For matched pairs the signed start-time error is
   ``detected.start - reference.start`` (positive = late). End-time and occupancy errors are
   reported where both sides carry the relevant value.

The default tolerance is :data:`DEFAULT_TOLERANCE_SECONDS`. It is a knob of *matching*, not
of the detector; it is reported with every evaluation run so results stay interpretable.
"""

from __future__ import annotations

from app.evaluation.model import (
    DetectedEvent,
    EventPair,
    LabelledEvent,
    MatchOutcome,
)

#: Default start-time tolerance for pairing a reference and a detected event (seconds).
DEFAULT_TOLERANCE_SECONDS = 5.0


def _intervals_overlap(label: LabelledEvent, detected: DetectedEvent) -> bool:
    if label.end_time is None or detected.end_time is None:
        return False
    return label.start_time <= detected.end_time and detected.start_time <= label.end_time


def _start_diff_seconds(label: LabelledEvent, detected: DetectedEvent) -> float:
    return (detected.start_time - label.start_time).total_seconds()


def _corresponds(label: LabelledEvent, detected: DetectedEvent, tolerance: float) -> bool:
    if _intervals_overlap(label, detected):
        return True
    return abs(_start_diff_seconds(label, detected)) <= tolerance


def _pair(label: LabelledEvent, detected: DetectedEvent) -> EventPair:
    start_error = _start_diff_seconds(label, detected)
    end_error: float | None = None
    if label.end_time is not None and detected.end_time is not None:
        end_error = (detected.end_time - label.end_time).total_seconds()
    occupancy_error: int | None = None
    if label.occupancy is not None and detected.occupancy is not None:
        occupancy_error = detected.occupancy - label.occupancy
    return EventPair(
        label=label,
        detected=detected,
        start_error_seconds=start_error,
        end_error_seconds=end_error,
        occupancy_error=occupancy_error,
    )


def match_activity(
    labels: list[LabelledEvent],
    detected: list[DetectedEvent],
    *,
    tolerance_seconds: float = DEFAULT_TOLERANCE_SECONDS,
) -> MatchOutcome:
    """Match one activity's reference and detected events (rules above).

    ``labels`` and ``detected`` must already be from the same activity/camera scope; the
    caller (:func:`app.evaluation.metrics.evaluate`) groups by ``(camera_id, event_type)``.
    """
    if tolerance_seconds < 0:
        raise ValueError("tolerance_seconds must be >= 0")

    candidates: list[tuple[float, int, int]] = []
    for label_index, label in enumerate(labels):
        for detected_index, detection in enumerate(detected):
            if _corresponds(label, detection, tolerance_seconds):
                candidates.append(
                    (abs(_start_diff_seconds(label, detection)), label_index, detected_index)
                )
    candidates.sort()

    used_labels: set[int] = set()
    used_detected: set[int] = set()
    outcome = MatchOutcome()
    for _, label_index, detected_index in candidates:
        if label_index in used_labels or detected_index in used_detected:
            continue
        used_labels.add(label_index)
        used_detected.add(detected_index)
        outcome.pairs.append(_pair(labels[label_index], detected[detected_index]))

    outcome.false_negatives = [
        label for index, label in enumerate(labels) if index not in used_labels
    ]
    outcome.false_positives = [
        detection for index, detection in enumerate(detected) if index not in used_detected
    ]
    return outcome
