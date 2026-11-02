"""Per-camera tracker: ByteTrack plus a dependency-free IoU tracker (FR-12).

:class:`ByteTrackTracker` wraps ``supervision.ByteTrack`` (the tracker mandated by
``../workflow_requirements.md`` §7) and imports ``supervision``/NumPy lazily.
:class:`IoUTracker` is a small greedy IoU tracker used by dependency-free unit tests and as
an offline fallback; it keeps the same interface so the worker is tracker-agnostic.

Track ids are local, monotonically increasing per tracker instance and never reused within
an epoch. They are **not** identities (FR-13).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from vision.detection.detector import Detection


@dataclass(frozen=True)
class Track:
    """A tracked entity in the current frame."""

    track_id: int
    class_name: str
    confidence: float
    bbox: tuple[float, float, float, float]


class Tracker(Protocol):
    """Tracking component interface."""

    name: str

    def reset(self) -> None:
        """Clear all track state (called on every (re)connection)."""

    def update(self, detections: list[Detection]) -> list[Track]:
        """Associate ``detections`` with existing tracks and return current tracks."""


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    intersection = iw * ih
    if intersection <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


class IoUTracker:
    """Greedy IoU tracker with a short track-miss grace period."""

    name = "iou"

    def __init__(self, *, iou_threshold: float = 0.3, max_missed: int = 10) -> None:
        self._iou_threshold = iou_threshold
        self._max_missed = max_missed
        self._next_id = 1
        self._states: dict[int, tuple[tuple[float, float, float, float], int, str]] = {}

    def reset(self) -> None:
        self._next_id = 1
        self._states.clear()

    def update(self, detections: list[Detection]) -> list[Track]:
        unmatched_detections = list(range(len(detections)))
        matched: list[tuple[int, int]] = []  # (track_id, detection_index)

        candidates: list[tuple[float, int, int]] = []
        for track_id, (bbox, _, _) in self._states.items():
            for det_index, detection in enumerate(detections):
                score = _iou(bbox, detection.bbox)
                if score >= self._iou_threshold:
                    candidates.append((score, track_id, det_index))
        candidates.sort(reverse=True)

        used_tracks: set[int] = set()
        for _score, track_id, det_index in candidates:
            if track_id in used_tracks or det_index not in unmatched_detections:
                continue
            used_tracks.add(track_id)
            unmatched_detections.remove(det_index)
            matched.append((track_id, det_index))

        # Update matched tracks.
        for track_id, det_index in matched:
            detection = detections[det_index]
            self._states[track_id] = (detection.bbox, 0, detection.class_name)

        # Retire tracks that were not seen this frame.
        for track_id in list(self._states):
            if track_id in used_tracks:
                continue
            bbox, missed, class_name = self._states[track_id]
            missed += 1
            if missed > self._max_missed:
                del self._states[track_id]
            else:
                self._states[track_id] = (bbox, missed, class_name)

        # Create tracks for unmatched detections.
        for det_index in unmatched_detections:
            detection = detections[det_index]
            track_id = self._next_id
            self._next_id += 1
            self._states[track_id] = (detection.bbox, 0, detection.class_name)

        return [
            Track(track_id=track_id, class_name=name, confidence=0.0, bbox=bbox)
            for track_id, (bbox, _, name) in self._states.items()
        ]


class ByteTrackTracker:
    """``supervision.ByteTrack`` adapter."""

    name = "bytetrack"

    def __init__(self) -> None:
        self._tracker: Any | None = None

    def _ensure(self) -> Any:
        if self._tracker is None:
            import supervision as sv  # lazy

            self._tracker = sv.ByteTrack()
        return self._tracker

    def reset(self) -> None:
        self._tracker = None

    def update(self, detections: list[Detection]) -> list[Track]:
        import numpy as np
        import supervision as sv

        tracker = self._ensure()
        if detections:
            xyxy = np.array([d.bbox for d in detections], dtype=float)
            confidence = np.array([d.confidence for d in detections], dtype=float)
            class_id = np.array([d.class_id for d in detections], dtype=int)
            sv_detections = sv.Detections(xyxy=xyxy, confidence=confidence, class_id=class_id)
            names = {d.class_id: d.class_name for d in detections}
        else:
            sv_detections = sv.Detections.empty()
            names = {}

        tracked = tracker.update_with_detections(sv_detections)
        tracks: list[Track] = []
        tracker_ids = getattr(tracked, "tracker_id", None)
        if tracker_ids is None:
            return tracks
        for index, track_id in enumerate(tracker_ids):
            if track_id is None:
                continue
            class_id = int(tracked.class_id[index])
            tracks.append(
                Track(
                    track_id=int(track_id),
                    class_name=names.get(class_id, "object"),
                    confidence=float(tracked.confidence[index]),
                    bbox=tuple(float(v) for v in tracked.xyxy[index]),
                )
            )
        return tracks
