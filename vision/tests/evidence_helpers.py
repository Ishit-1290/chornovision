"""Shared builders/fakes for the Phase 6 evidence and handoff tests."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.events.types import (
    Certainty,
    EventAction,
    EventSeverity,
    EventSnapshot,
    EventStatus,
    EventTransition,
    EventType,
)

START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return START + timedelta(seconds=seconds)


def make_transition(
    event_id: str = "event-1",
    *,
    status: EventStatus = EventStatus.ACTIVE,
    action: EventAction = EventAction.OPENED,
    camera_id: int = 1,
    start_offset: float = 0.0,
    trigger_offset: float = 0.0,
    end_offset: float | None = None,
    event_type: EventType = EventType.PERSON_ENTERING,
    state_version: int = 1,
    confidence: float | None = 0.9,
    certainty: Certainty = Certainty.HIGH,
) -> EventTransition:
    """Build a valid transition without running the engine."""
    end_time = None if end_offset is None else at(end_offset)
    last_updated = at(end_offset if end_offset is not None else trigger_offset)
    snapshot = EventSnapshot(
        event_id=event_id,
        camera_id=camera_id,
        event_type=event_type,
        start_time=at(start_offset),
        trigger_time=at(trigger_offset),
        last_updated_at=last_updated,
        end_time=end_time,
        status=status,
        severity=EventSeverity.WARNING,
        state_version=state_version,
        confidence=confidence,
        certainty=certainty,
    )
    return EventTransition(action=action, event=snapshot)


def completed_transition(event_id: str = "event-1", *, state_version: int = 2) -> EventTransition:
    return make_transition(
        event_id,
        status=EventStatus.COMPLETED,
        action=EventAction.RESOLVED,
        end_offset=5.0,
        state_version=state_version,
    )


@dataclass
class Buffered:
    """A minimal rolling-buffer item (image + monotonic time)."""

    image: Any
    monotonic: float
    arrival_utc: datetime


class FakeStore:
    """An injectable evidence store that records calls (and can block)."""

    def __init__(self, *, block: threading.Event | None = None) -> None:
        self._lock = threading.Lock()
        self._block = block
        self.snapshots: list[dict[str, Any]] = []
        self.clips: list[dict[str, Any]] = []

    def save_snapshot(self, *, camera_id, event_id, captured_at, image):
        from vision.evidence.store import EvidenceRecord

        if self._block is not None:
            self._block.wait(5.0)
        with self._lock:
            self.snapshots.append({"camera_id": camera_id, "event_id": event_id, "image": image})
        return EvidenceRecord(
            event_id=event_id,
            media_type="snapshot",
            status="available",
            relative_path=f"camera-{camera_id}/snapshot.jpg",
            file_size_bytes=10,
            duration_seconds=None,
            captured_at=captured_at,
        )

    def save_clip(self, *, camera_id, event_id, captured_at, frames, fps):
        from vision.evidence.store import EvidenceRecord

        if self._block is not None:
            self._block.wait(5.0)
        with self._lock:
            self.clips.append(
                {
                    "camera_id": camera_id,
                    "event_id": event_id,
                    "frames": list(frames),
                    "fps": fps,
                }
            )
        return EvidenceRecord(
            event_id=event_id,
            media_type="clip",
            status="available",
            relative_path=f"camera-{camera_id}/clip.mp4",
            file_size_bytes=20,
            duration_seconds=len(frames) / fps if fps else None,
            captured_at=captured_at,
        )


class RecordCollector:
    """Thread-safe list of evidence records passed to the registrar."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[Any] = []

    def __call__(self, record: Any) -> None:
        with self._lock:
            self._records.append(record)

    def all(self) -> list[Any]:
        with self._lock:
            return list(self._records)

    def by_type(self, media_type: str) -> list[Any]:
        return [record for record in self.all() if record.media_type == media_type]
