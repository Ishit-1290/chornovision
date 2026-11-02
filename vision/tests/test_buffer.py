"""Rolling frame-buffer tests (FR-35, NFR-04)."""

from __future__ import annotations

import pytest

from vision.buffer import RollingFrameBuffer


class Sized:
    def __init__(self, nbytes: int) -> None:
        self.nbytes = nbytes


def test_append_within_item_limit() -> None:
    buffer = RollingFrameBuffer(max_items=3, max_bytes=1000)
    for _ in range(3):
        assert buffer.append(Sized(10)) is True
    assert len(buffer) == 3
    assert buffer.bytes_used == 30


def test_oldest_item_is_evicted_at_item_limit() -> None:
    buffer = RollingFrameBuffer(max_items=2, max_bytes=1000)
    items = [Sized(10), Sized(20), Sized(30)]
    for item in items:
        buffer.append(item)
    assert buffer.snapshot() == [items[1], items[2]]
    assert buffer.bytes_used == 50


def test_byte_budget_evicts_oldest() -> None:
    buffer = RollingFrameBuffer(max_items=10, max_bytes=25)
    a, b, c = Sized(10), Sized(10), Sized(10)
    buffer.append(a)
    buffer.append(b)
    buffer.append(c)  # 30 > 25 → evict a
    assert buffer.snapshot() == [b, c]
    assert buffer.bytes_used == 20


def test_oversized_item_is_refused_without_storing() -> None:
    buffer = RollingFrameBuffer(max_items=4, max_bytes=10)
    assert buffer.append(Sized(11)) is False
    assert len(buffer) == 0
    assert buffer.refused == 1
    assert buffer.bytes_used == 0


def test_clear_resets_contents_and_bytes() -> None:
    buffer = RollingFrameBuffer(max_items=4, max_bytes=100)
    buffer.append(Sized(10))
    buffer.append(Sized(10))
    buffer.clear()
    assert len(buffer) == 0
    assert buffer.bytes_used == 0


def test_custom_size_function_is_used() -> None:
    buffer = RollingFrameBuffer(max_items=2, max_bytes=100, size_of=lambda item: len(item))
    buffer.append("abc")
    buffer.append("de")
    assert buffer.bytes_used == 5
    assert buffer.snapshot() == ["abc", "de"]


def test_extend_appends_in_order() -> None:
    buffer = RollingFrameBuffer(max_items=5, max_bytes=100)
    buffer.extend([Sized(1), Sized(1), Sized(1)])
    assert len(buffer) == 3


def test_default_size_uses_image_attribute() -> None:
    class Holder:
        def __init__(self) -> None:
            self.image = Sized(42)

    buffer = RollingFrameBuffer(max_items=2, max_bytes=100)
    buffer.append(Holder())
    assert buffer.bytes_used == 42


@pytest.mark.parametrize(("items", "size", "kwargs"), [(0, 10, {}), (1, 0, {})])
def test_invalid_bounds_raise(items: int, size: int, kwargs: dict) -> None:
    with pytest.raises(ValueError):
        RollingFrameBuffer(max_items=items, max_bytes=size, **kwargs)
