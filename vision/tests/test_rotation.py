"""Detection-time frame rotation tests (D-72).

The worker rotates a sideways frame for the detector and maps boxes back into the original
camera frame. These tests pin the rotation maths so a zone never has to move: the mapping
must be the exact inverse of the rotation OpenCV applies.
"""

from __future__ import annotations

import pytest

from vision.ingestion.rotation import (
    ROTATIONS,
    map_bbox_from_rotated,
    normalize_rotation,
    rotate_frame,
    rotated_size,
)

# --- normalisation -------------------------------------------------------------


@pytest.mark.parametrize("value", ROTATIONS)
def test_supported_rotations_are_kept(value: int) -> None:
    assert normalize_rotation(value) == value


def test_missing_or_unsupported_rotations_mean_zero() -> None:
    assert normalize_rotation(None) == 0
    assert normalize_rotation(0) == 0
    assert normalize_rotation(45) == 0
    assert normalize_rotation(360) == 0
    assert normalize_rotation("90") == 0
    assert normalize_rotation(90.0) == 0


def test_booleans_are_never_rotations() -> None:
    # ``bool`` is an ``int`` subclass; True must not mean 1 (an unsupported rotation).
    assert normalize_rotation(True) == 0
    assert normalize_rotation(False) == 0


# --- geometry ------------------------------------------------------------------


@pytest.mark.parametrize("rotation", (90, 270))
def test_quarter_turns_swap_the_dimensions(rotation: int) -> None:
    assert rotated_size(960, 540, rotation) == (540, 960)


@pytest.mark.parametrize("rotation", (0, 180))
def test_half_and_no_rotation_keep_the_dimensions(rotation: int) -> None:
    assert rotated_size(960, 540, rotation) == (960, 540)


def test_zero_rotation_is_a_passthrough() -> None:
    image = object()
    assert rotate_frame(image, 0) is image


@pytest.mark.parametrize("rotation", (90, 180, 270))
def test_rotate_frame_applies_the_requested_quarter_turn(rotation: int) -> None:
    np = pytest.importorskip("numpy")
    image = np.zeros((48, 64, 3), dtype=np.uint8)
    rotated = rotate_frame(image, rotation)
    width, height = rotated_size(64, 48, rotation)
    assert rotated.shape == (height, width, 3)


# --- box mapping round-trip ----------------------------------------------------


def _pixel_bbox(image):
    """Bounding box (continuous extents) of the non-zero pixels in ``image``."""
    np = pytest.importorskip("numpy")
    rows, columns = np.nonzero(image[:, :, 0])
    assert rows.size and columns.size  # the rectangle must survive the rotation
    return (
        float(columns.min()),
        float(rows.min()),
        float(columns.max() + 1),
        float(rows.max() + 1),
    )


@pytest.mark.parametrize("rotation", (90, 180, 270))
def test_mapping_is_the_exact_inverse_of_the_rotation(rotation: int) -> None:
    """A known rectangle detected in the rotated frame maps back onto itself."""
    np = pytest.importorskip("numpy")
    source_width, source_height = 64, 48
    original = (10.0, 4.0, 37.0, 30.0)  # deliberately asymmetric

    source = np.zeros((source_height, source_width, 3), dtype=np.uint8)
    x1, y1, x2, y2 = (int(value) for value in original)
    source[y1:y2, x1:x2] = 255

    rotated = rotate_frame(source, rotation)
    detected = _pixel_bbox(rotated)
    assert detected != original  # the box really moved

    mapped = map_bbox_from_rotated(detected, rotation, source_width, source_height)
    assert mapped == pytest.approx(original)


@pytest.mark.parametrize("rotation", (0, 90, 180, 270))
def test_mapping_a_source_box_with_identity_rotation(rotation: int) -> None:
    box = (10.0, 20.0, 30.0, 40.0)
    if rotation == 0:
        assert map_bbox_from_rotated(box, rotation, 64, 48) == box
        return
    # Build the box as it would appear in the rotated frame, then map it back.
    width, height = rotated_size(64, 48, rotation)
    rotated_box = map_bbox_from_rotated(box, (360 - rotation) % 360, width, height)
    assert map_bbox_from_rotated(rotated_box, rotation, 64, 48) == pytest.approx(box)
