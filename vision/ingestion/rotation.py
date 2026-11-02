"""Frame rotation for cameras that publish a sideways picture (D-72).

A camera can stream a frame whose scene is rotated (for example a phone held in portrait
publishing a landscape frame). The pretrained person detector is trained on upright people
and reliably misses sideways ones, so the worker rotates the frame **for detection only**
and maps each detected box back into the original frame. Zones, boundaries, tracking and
every event rule keep working in the original (camera) frame, unchanged.

The helpers are pure and import OpenCV lazily, so their maths is unit-testable without a
decoder or model weights.
"""

from __future__ import annotations

from typing import Any

Box = tuple[float, float, float, float]

#: Supported clockwise rotations, in degrees.
ROTATIONS: tuple[int, ...] = (0, 90, 180, 270)


def normalize_rotation(value: Any) -> int:
    """Return a supported clockwise rotation; anything else means "no rotation" (0)."""
    if isinstance(value, bool):  # bool is an int subclass; never a rotation value
        return 0
    if isinstance(value, int) and value in ROTATIONS:
        return value
    return 0


def rotated_size(width: int, height: int, rotation: int) -> tuple[int, int]:
    """Dimensions of the frame after rotating ``width`` x ``height`` by ``rotation``."""
    if rotation in (90, 270):
        return height, width
    return width, height


def rotate_frame(image: Any, rotation: int) -> Any:
    """Rotate ``image`` clockwise by ``rotation`` degrees for the detector.

    Returns ``image`` unchanged for ``0`` (and for any unsupported value), so the common
    no-rotation path never touches OpenCV.
    """
    if rotation not in (90, 180, 270):
        return image
    import cv2  # lazy

    code = {
        90: cv2.ROTATE_90_CLOCKWISE,
        180: cv2.ROTATE_180,
        270: cv2.ROTATE_90_COUNTERCLOCKWISE,
    }[rotation]
    return cv2.rotate(image, code)


def map_bbox_from_rotated(
    bbox: Box,
    rotation: int,
    source_width: int,
    source_height: int,
) -> Box:
    """Map a pixel bounding box from the rotated frame back into the source frame.

    ``source_width``/``source_height`` describe the frame *before* rotation (the one the
    worker detected on is ``rotated_size(source_width, source_height, rotation)``). The
    inverse of an axis-aligned 90/180/270 rotation is itself axis-aligned, so the result is
    a bounding box in the source frame. Coordinates use continuous extents (``0..width``,
    ``0..height``), matching how detections are normalised downstream.
    """
    x1, y1, x2, y2 = (float(value) for value in bbox)
    width = float(source_width)
    height = float(source_height)

    if rotation == 90:
        # rotate CW: source (x, y) -> rotated (x' = width - y, y' = x)  [rotated is h x w]
        return (y1, height - x2, y2, height - x1)
    if rotation == 270:
        # rotate CCW: source (x, y) -> rotated (x' = y, y' = width - x)
        return (width - y2, x1, width - y1, x2)
    if rotation == 180:
        return (width - x2, height - y2, width - x1, height - y1)
    return (x1, y1, x2, y2)
