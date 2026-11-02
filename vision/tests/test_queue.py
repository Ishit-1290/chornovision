"""Bounded frame-queue tests (FR-07, NFR-04, NFR-05)."""

from __future__ import annotations

import threading
import time

import pytest

from vision.ingestion.queue import DropPolicy, FrameQueue

from .fakes import FakeClock


def test_put_and_get_preserve_order() -> None:
    queue = FrameQueue(4)
    for value in ("a", "b", "c"):
        assert queue.put(value) is True
    assert queue.depth == 3
    assert [queue.get(timeout=0.1) for _ in range(3)] == ["a", "b", "c"]
    assert queue.get(timeout=0.01) is None


def test_maxsize_must_be_positive() -> None:
    with pytest.raises(ValueError):
        FrameQueue(0)


def test_drop_oldest_evicts_the_oldest_frame() -> None:
    queue = FrameQueue(2, policy=DropPolicy.DROP_OLDEST)
    queue.put("a")
    queue.put("b")
    assert queue.put("c") is True
    assert queue.get(timeout=0.1) == "b"
    assert queue.get(timeout=0.1) == "c"
    assert queue.dropped == 1
    assert queue.max_depth == 2


def test_drop_newest_refuses_the_incoming_frame() -> None:
    queue = FrameQueue(2, policy=DropPolicy.DROP_NEWEST)
    queue.put("a")
    queue.put("b")
    assert queue.put("c") is False
    assert queue.get(timeout=0.1) == "a"
    assert queue.get(timeout=0.1) == "b"
    assert queue.get(timeout=0.1) is None
    assert queue.dropped == 1


def test_get_returns_none_on_timeout() -> None:
    queue = FrameQueue(1)
    started = time.monotonic()
    assert queue.get(timeout=0.05) is None
    assert time.monotonic() - started >= 0.04


def test_close_wakes_blocked_getters() -> None:
    queue = FrameQueue(1)
    result: list[object] = []

    def consumer() -> None:
        result.append(queue.get(timeout=5.0))

    thread = threading.Thread(target=consumer)
    thread.start()
    time.sleep(0.05)
    queue.close()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert result == [None]
    assert queue.closed is True


def test_put_after_close_is_refused() -> None:
    queue = FrameQueue(1)
    queue.close()
    assert queue.put("a") is False
    assert queue.depth == 0


def test_wake_does_not_lose_items() -> None:
    queue = FrameQueue(2)
    queue.put("a")
    queue.wake()
    assert queue.get(timeout=0.1) == "a"


def test_last_activity_tracks_operations() -> None:
    clock = FakeClock(100.0)
    queue = FrameQueue(2, clock=clock)
    clock.advance(5.0)
    queue.put("a")
    assert queue.last_activity == 105.0
