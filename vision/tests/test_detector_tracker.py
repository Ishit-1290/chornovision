"""Detector and tracker tests (FR-10, FR-12, FR-13)."""

from __future__ import annotations

import sys
import types

import pytest

from vision.detection.detector import (
    PERSON_CLASS_NAME,
    Detection,
    NullDetector,
    YoloDetector,
)
from vision.tracking.tracker import ByteTrackTracker, IoUTracker, _iou

# --- null detector --------------------------------------------------------------


def test_null_detector_returns_nothing() -> None:
    detector = NullDetector()
    detector.load()
    assert detector.detect(object()) == []
    detector.close()
    assert detector.name == "null"


# --- IoU tracker (dependency-free) ----------------------------------------------


def _detection(bbox, *, class_id: int = 0, confidence: float = 0.9) -> Detection:
    return Detection(
        class_id=class_id, class_name=PERSON_CLASS_NAME, confidence=confidence, bbox=bbox
    )


def test_iou_tracker_creates_and_reuses_a_track() -> None:
    tracker = IoUTracker(iou_threshold=0.3)
    first = tracker.update([_detection((0.0, 0.0, 10.0, 10.0))])
    assert len(first) == 1
    track_id = first[0].track_id
    second = tracker.update([_detection((1.0, 1.0, 11.0, 11.0))])
    assert [track.track_id for track in second] == [track_id]


def test_iou_tracker_assigns_new_ids_to_new_objects() -> None:
    tracker = IoUTracker()
    first = tracker.update([_detection((0.0, 0.0, 10.0, 10.0))])
    second = tracker.update(
        [_detection((0.0, 0.0, 10.0, 10.0)), _detection((100.0, 100.0, 110.0, 110.0))]
    )
    assert {track.track_id for track in second} >= {first[0].track_id}
    assert len(second) == 2


def test_iou_tracker_retires_tracks_after_grace_period() -> None:
    tracker = IoUTracker(max_missed=2)
    tracker.update([_detection((0.0, 0.0, 10.0, 10.0))])
    for _ in range(2):
        tracker.update([])
    assert tracker.update([]) == []


def test_iou_tracker_reset_clears_state_and_ids() -> None:
    tracker = IoUTracker()
    first = tracker.update([_detection((0.0, 0.0, 10.0, 10.0))])
    assert first[0].track_id == 1
    tracker.reset()
    again = tracker.update([_detection((0.0, 0.0, 10.0, 10.0))])
    assert again[0].track_id == 1


def test_iou_helper() -> None:
    assert _iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert _iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    assert _iou((0, 0, 0, 0), (0, 0, 0, 0)) == 0.0


# --- YOLO detector --------------------------------------------------------------


class _FakeVector:
    def __init__(self, value: float) -> None:
        self._value = value

    def item(self) -> float:
        return self._value

    def tolist(self) -> list[float]:
        return list(self._value)


class _FakeBoxes:
    def __init__(self, class_ids, confidences, boxes) -> None:
        self.cls = [_FakeVector(v) for v in class_ids]
        self.conf = [_FakeVector(v) for v in confidences]
        self.xyxy = [_FakeVector(v) for v in boxes]

    def __len__(self) -> int:
        return len(self.cls)


class _FakeResult:
    def __init__(self, boxes) -> None:
        self.boxes = boxes


class _FakeModel:
    def __init__(self, boxes) -> None:
        self._boxes = boxes
        self.names = {0: PERSON_CLASS_NAME, 1: "bicycle"}
        self.calls: list[dict] = []

    def predict(self, **kwargs):
        self.calls.append(kwargs)
        return [_FakeResult(self._boxes)]


def _install_fake_ultralytics(monkeypatch, model) -> None:
    module = types.ModuleType("ultralytics")
    module.YOLO = lambda weights: model  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ultralytics", module)


def test_yolo_detect_before_load_raises() -> None:
    detector = YoloDetector(weights="does-not-matter.pt")
    with pytest.raises(RuntimeError):
        detector.detect(object())


def test_yolo_loads_and_returns_person_detections(monkeypatch) -> None:
    boxes = _FakeBoxes([0], [0.9], [[0.0, 0.0, 10.0, 20.0]])
    model = _FakeModel(boxes)
    _install_fake_ultralytics(monkeypatch, model)

    detector = YoloDetector(weights="fake.pt", person_only=True)
    detector.load()
    assert detector._model is model
    detections = detector.detect(object())
    assert len(detections) == 1
    detection = detections[0]
    assert detection.class_name == PERSON_CLASS_NAME
    assert detection.confidence == 0.9
    assert detection.bbox == (0.0, 0.0, 10.0, 20.0)
    # Confidence threshold is passed through to the model unchanged.
    assert model.calls[0]["conf"] == detector.confidence


def test_yolo_person_only_filters_other_classes(monkeypatch) -> None:
    boxes = _FakeBoxes([0, 1], [0.9, 0.8], [[0, 0, 10, 10], [20, 20, 30, 30]])
    model = _FakeModel(boxes)
    _install_fake_ultralytics(monkeypatch, model)

    person_only = YoloDetector(weights="fake.pt", person_only=True)
    person_only.load()
    assert len(person_only.detect(object())) == 1

    everything = YoloDetector(weights="fake.pt", person_only=False)
    everything.load()
    names = {detection.class_name for detection in everything.detect(object())}
    assert names == {PERSON_CLASS_NAME, "bicycle"}


def test_yolo_close_releases_model(monkeypatch) -> None:
    model = _FakeModel(_FakeBoxes([], [], []))
    _install_fake_ultralytics(monkeypatch, model)
    detector = YoloDetector(weights="fake.pt")
    detector.load()
    detector.close()
    assert detector._model is None
    with pytest.raises(RuntimeError):
        detector.detect(object())


def test_yolo_name_includes_weights() -> None:
    assert YoloDetector(weights="yolo11n.pt").name == "yolo:yolo11n.pt"


# --- ByteTrack (optional dependency) --------------------------------------------


def test_bytetrack_assigns_track_ids() -> None:
    pytest.importorskip("supervision")
    pytest.importorskip("numpy")
    tracker = ByteTrackTracker()
    tracker.reset()
    tracks = tracker.update([_detection((0.0, 0.0, 50.0, 100.0))])
    assert len(tracks) == 1
    assert tracks[0].track_id is not None
    assert tracks[0].class_name == PERSON_CLASS_NAME


def test_bytetrack_handles_empty_detections() -> None:
    pytest.importorskip("supervision")
    pytest.importorskip("numpy")
    tracker = ByteTrackTracker()
    tracker.reset()
    assert tracker.update([]) == []
    tracker.reset()
    assert tracker.update([]) == []
