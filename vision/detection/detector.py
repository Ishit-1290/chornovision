"""Pretrained YOLO detector plus a dependency-free null detector (FR-10).

:class:`YoloDetector` wraps Ultralytics YOLO. ``ultralytics``/``torch`` are imported inside
:meth:`YoloDetector.load`, and the model is created there too: constructing the detector or
importing this module never loads weights or touches the network. Weights are explicit
configuration (``VISION_DETECTOR_WEIGHTS``) so a run is reproducible; the first real run may
download them, which normal unit tests deliberately avoid by using :class:`NullDetector`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

#: COCO class index for "person" (the Phase 4 vertical slice).
PERSON_CLASS_ID = 0
PERSON_CLASS_NAME = "person"


@dataclass(frozen=True)
class Detection:
    """One detection observation. Never a temporal event (FR-11)."""

    class_id: int
    class_name: str
    confidence: float
    #: ``(x1, y1, x2, y2)`` in pixel coordinates.
    bbox: tuple[float, float, float, float]


class Detector(Protocol):
    """Detection component interface."""

    name: str

    def load(self) -> None:
        """Load model weights. Called lazily by the worker."""

    def detect(self, image: Any) -> list[Detection]:
        """Return detections for a prepared frame."""

    def close(self) -> None:
        """Release model resources."""


class NullDetector:
    """A detector that returns no observations.

    Used when detection is explicitly disabled and by deterministic tests that must not
    download or load model weights.
    """

    name = "null"

    def load(self) -> None:
        return None

    def detect(self, image: Any) -> list[Detection]:
        return []

    def close(self) -> None:
        return None


class YoloDetector:
    """Ultralytics YOLO detector (pretrained weights, person-only by default)."""

    def __init__(
        self,
        *,
        weights: str = "yolo11n.pt",
        device: str = "cpu",
        confidence: float = 0.25,
        iou: float = 0.7,
        imgsz: int = 640,
        person_only: bool = True,
        model: Any | None = None,
    ) -> None:
        self.weights = weights
        self.device = device
        self.confidence = confidence
        self.iou = iou
        self.imgsz = imgsz
        self.person_only = person_only
        self._model = model
        self._names: dict[int, str] = {}

    @property
    def name(self) -> str:
        return f"yolo:{self.weights}"

    def load(self) -> None:
        """Import Ultralytics and load the model (may download weights once)."""
        if self._model is not None:
            return
        from ultralytics import YOLO  # lazy, heavy import

        model = YOLO(self.weights)
        self._model = model
        names = getattr(model, "names", {}) or {}
        if isinstance(names, dict):
            self._names = {int(k): str(v) for k, v in names.items()}
        elif isinstance(names, Sequence):
            self._names = {i: str(v) for i, v in enumerate(names)}

    def detect(self, image: Any) -> list[Detection]:
        if self._model is None:
            raise RuntimeError("YoloDetector.detect called before load()")
        results = self._model.predict(
            source=image,
            conf=self.confidence,
            iou=self.iou,
            imgsz=self.imgsz,
            device=self.device,
            verbose=False,
        )
        detections: list[Detection] = []
        for result in results or []:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            detections.extend(self._parse_boxes(boxes))
        return detections

    def _parse_boxes(self, boxes: Any) -> list[Detection]:
        parsed: list[Detection] = []
        try:
            count = len(boxes)
        except TypeError:  # pragma: no cover - defensive
            return parsed
        for index in range(count):
            class_id = int(boxes.cls[index].item())
            if self.person_only and class_id != PERSON_CLASS_ID:
                continue
            confidence = float(boxes.conf[index].item())
            coords = boxes.xyxy[index].tolist()
            if len(coords) != 4:  # pragma: no cover - defensive
                continue
            x1, y1, x2, y2 = (float(v) for v in coords)
            parsed.append(
                Detection(
                    class_id=class_id,
                    class_name=self._names.get(class_id, PERSON_CLASS_NAME),
                    confidence=confidence,
                    bbox=(x1, y1, x2, y2),
                )
            )
        return parsed

    def close(self) -> None:
        self._model = None
        self._names = {}
