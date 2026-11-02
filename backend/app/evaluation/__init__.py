"""Deterministic event-evaluation tooling (Phase 9; G §16.2, W §15).

This package turns manually annotated **reference events** and the system's **detected
events** into the detection-quality metrics the guidelines require: per-activity precision,
recall, F1, false-positive/false-negative counts, event-boundary timing error, and (for the
occupancy activities) occupancy counting error.

Nothing here runs inside the event pipeline: it is an offline, pure-Python analysis utility
with explicit matching rules (see :mod:`app.evaluation.matching`). It contains no LLM and no
text generation, consistent with CON-01.

Public surface:

* :func:`app.evaluation.evaluate` — score two event collections and return a report.
* :class:`app.evaluation.model.LabelledEvent` / ``DetectedEvent`` — the two input shapes.
* :func:`app.evaluation.dataset.load_labels` / ``load_detected`` / ``detected_from_rows`` —
  loaders for the JSON label format and for persisted events.
"""

from __future__ import annotations

from app.evaluation.metrics import evaluate
from app.evaluation.model import (
    ActivityMetrics,
    DetectedEvent,
    EvaluationReport,
    LabelledEvent,
)

__all__ = [
    "ActivityMetrics",
    "DetectedEvent",
    "EvaluationReport",
    "LabelledEvent",
    "evaluate",
]
