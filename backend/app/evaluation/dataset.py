"""Load labelled reference events and detected events for evaluation (Phase 9; G §16.2).

Two input sources are supported:

* the project's **JSON label format** (see ``docs/EVALUATION.md``) for manually annotated
  reference events, and the same shape for a detected-event export;
* the persisted ``events`` rows (ORM objects or API dicts) for real system output.

The detected-event loader reads the occupancy count from the event ``attributes``
(``occupancy_count``), so occupancy counting error can be computed for matched events.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from app.evaluation.model import DetectedEvent, LabelledEvent
from app.utils import ensure_utc


def _parse_time(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value)
    return ensure_utc(datetime.fromisoformat(value))


def _event_records(payload: Any) -> list[dict[str, Any]]:
    """Accept either a bare list of events or ``{"events": [...]}``."""
    if isinstance(payload, dict):
        records = payload.get("events")
    else:
        records = payload
    if not isinstance(records, list):
        raise ValueError("label file must contain a JSON list or an object with an 'events' list")
    return [record for record in records if isinstance(record, dict)]


def load_labels(path: str | Path) -> list[LabelledEvent]:
    """Load reference events from the JSON label format."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    labels: list[LabelledEvent] = []
    for record in _event_records(payload):
        labels.append(
            LabelledEvent(
                camera_id=int(record["camera_id"]),
                event_type=str(record["event_type"]),
                start_time=_parse_time(record["start_time"]),
                end_time=_parse_time(record.get("end_time")),
                zone_id=record.get("zone_id"),
                occupancy=_optional_int(record.get("occupancy")),
                uncertain=bool(record.get("uncertain", False)),
            )
        )
    return labels


def load_detected(path: str | Path) -> list[DetectedEvent]:
    """Load detected events from a JSON export (same shape as the label format)."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    detected: list[DetectedEvent] = []
    for record in _event_records(payload):
        detected.append(
            DetectedEvent(
                camera_id=int(record["camera_id"]),
                event_type=str(record["event_type"]),
                start_time=_parse_time(record["start_time"]),
                end_time=_parse_time(record.get("end_time")),
                event_id=record.get("event_id"),
                zone_id=record.get("zone_id"),
                occupancy=_optional_int(record.get("occupancy")),
            )
        )
    return detected


def detected_from_rows(rows: Iterable[Any]) -> list[DetectedEvent]:
    """Convert persisted event rows (ORM objects or API dicts) to detected events."""
    detected: list[DetectedEvent] = []
    for row in rows:
        detected.append(
            DetectedEvent(
                camera_id=int(_field(row, "camera_id")),
                event_type=str(_field(row, "event_type")),
                start_time=_parse_time(_field(row, "start_time")),
                end_time=_parse_time(_field(row, "end_time")),
                event_id=_str_or_none(_field(row, "event_id")),
                zone_id=_str_or_none(_field(row, "zone_id")),
                occupancy=_occupancy_from_attributes(_field(row, "attributes")),
            )
        )
    return detected


def _field(row: Any, name: str) -> Any:
    if isinstance(row, dict):
        return row.get(name)
    return getattr(row, name, None)


def _str_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _occupancy_from_attributes(attributes: Any) -> int | None:
    if isinstance(attributes, dict):
        return _optional_int(attributes.get("occupancy_count"))
    return None
