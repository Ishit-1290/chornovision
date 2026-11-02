"""Frame validation, sampling, and preparation tests (FR-09, FR-15)."""

from __future__ import annotations

import pytest

from vision.ingestion.prepare import (
    SamplingPolicy,
    is_valid_frame,
    prepare_frame,
    resize_width,
)

from .fakes import FakeClock, FakeImage

# --- validation -----------------------------------------------------------------


def test_none_is_invalid() -> None:
    assert is_valid_frame(None) is False


def test_object_without_shape_is_invalid() -> None:
    assert is_valid_frame(object()) is False


def test_planar_and_degenerate_shapes() -> None:
    assert is_valid_frame(FakeImage()) is True
    assert is_valid_frame(FakeImage(height=0)) is False
    assert is_valid_frame(FakeImage(width=0)) is False


def test_non_numeric_shape_is_invalid() -> None:
    class Weird:
        shape = ("a", "b", 3)

    assert is_valid_frame(Weird()) is False


# --- sampling -------------------------------------------------------------------


def test_sampling_accepts_first_frame_then_throttles() -> None:
    clock = FakeClock(0.0)
    policy = SamplingPolicy(10.0, clock=clock)  # interval = 0.1 s
    assert policy.should_process() is True
    assert policy.should_process() is False
    clock.advance(0.05)
    assert policy.should_process() is False
    clock.advance(0.05)
    assert policy.should_process() is True


def test_sampling_reset_allows_the_next_frame() -> None:
    clock = FakeClock(0.0)
    policy = SamplingPolicy(1.0, clock=clock)
    assert policy.should_process() is True
    assert policy.should_process() is False
    policy.reset()
    assert policy.should_process() is True


def test_sampling_rejects_non_positive_target() -> None:
    with pytest.raises(ValueError):
        SamplingPolicy(0.0)


def test_sampling_interval_is_reported() -> None:
    policy = SamplingPolicy(4.0)
    assert policy.target_interval == 0.25


# --- preparation ----------------------------------------------------------------


def test_prepare_without_resizing_returns_same_object() -> None:
    image = FakeImage()
    assert prepare_frame(image, width=0) is image


def test_prepare_none_is_passthrough() -> None:
    assert prepare_frame(None, width=320) is None


def test_resize_changes_width_and_preserves_aspect_ratio() -> None:
    np = pytest.importorskip("numpy")
    image = np.zeros((48, 64, 3), dtype=np.uint8)
    resized = resize_width(image, 32)
    assert resized.shape == (24, 32, 3)


def test_resize_is_a_noop_when_width_matches() -> None:
    np = pytest.importorskip("numpy")
    image = np.zeros((48, 64, 3), dtype=np.uint8)
    assert resize_width(image, 64) is image
