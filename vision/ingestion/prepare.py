"""Frame validation, sampling policy, and preparation (FR-09, FR-15).

Nothing here imports NumPy or OpenCV at module load; resizing imports OpenCV lazily and is
skipped entirely when ``process_width`` is 0. The sampling policy is pure Python so its
behaviour (and its effect on temporal accuracy) is unit-testable without a decoder.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


def is_valid_frame(image: Any) -> bool:
    """Return ``True`` when ``image`` looks like a decodable 2-D+ frame.

    Guards the pipeline against ``None``, non-array objects, and degenerate shapes such as a
    0-pixel frame reported by a flaky decoder (FR-07: handle invalid frames explicitly).
    """
    if image is None:
        return False
    shape = getattr(image, "shape", None)
    if shape is None:
        return False
    try:
        dims = [int(d) for d in shape[:2]]
    except (TypeError, ValueError):
        return False
    return len(dims) == 2 and all(d > 0 for d in dims)


class SamplingPolicy:
    """Time-based frame sampler with a documented, configurable target FPS.

    Frames that arrive sooner than ``1 / target_fps`` after the last processed frame are
    skipped. Skipping is *not* silent: the caller records each skip in the metrics snapshot
    so the effect on brief events and temporal accuracy is observable (G §14.2).
    """

    def __init__(
        self,
        target_fps: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if target_fps <= 0:
            raise ValueError("target_fps must be > 0")
        self._interval = 1.0 / target_fps
        self._clock = clock
        self._last_processed: float | None = None

    def should_process(self, now: float | None = None) -> bool:
        """Return ``True`` when this frame should be processed, updating the window."""
        moment = self._clock() if now is None else now
        if self._last_processed is None or (moment - self._last_processed) >= self._interval:
            self._last_processed = moment
            return True
        return False

    def reset(self) -> None:
        self._last_processed = None

    @property
    def target_interval(self) -> float:
        return self._interval


def prepare_frame(image: Any, *, width: int = 0) -> Any:
    """Return a frame prepared for detection.

    Resizing (when ``width > 0``) preserves aspect ratio and uses area interpolation, which
    does not discard the information activities rely on (FR-09). Format conversion and
    normalisation are the detector's responsibility.
    """
    if width <= 0 or image is None:
        return image
    return resize_width(image, width)


def resize_width(image: Any, width: int) -> Any:
    """Resize ``image`` so its width equals ``width`` (aspect ratio preserved)."""
    import cv2  # lazy

    shape = getattr(image, "shape", None)
    if not shape or len(shape) < 2:
        return image
    height, current_width = int(shape[0]), int(shape[1])
    if current_width == width or current_width <= 0:
        return image
    scale = width / float(current_width)
    target_height = max(1, int(round(height * scale)))
    return cv2.resize(image, (width, target_height), interpolation=cv2.INTER_AREA)
