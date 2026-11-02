"""Evidence capture-window manager tests (Phase 6; FR-36, FR-37)."""

from __future__ import annotations

import threading
import time

import pytest

from vision.evidence.manager import EvidenceManager, EvidencePolicy

from .evidence_helpers import Buffered, FakeStore, RecordCollector, make_transition
from .fakes import FakeImage, wait_until

POLICY = EvidencePolicy(
    enabled=True,
    pre_event_seconds=5.0,
    post_event_seconds=0.0,
    snapshot_enabled=True,
    clip_fps=1.0,
    clip_max_frames=100,
)


class FakeBuffer:
    def __init__(self, frames: list[Buffered]) -> None:
        self.frames = frames

    def snapshot(self) -> list[Buffered]:
        return list(self.frames)


def _manager(
    policy: EvidencePolicy = POLICY,
    *,
    store: FakeStore | None = None,
    registrar: RecordCollector | None = None,
    buffer: FakeBuffer | None = None,
    encoder_queue_maxsize: int = 16,
    rotation: int = 0,
) -> tuple[EvidenceManager, FakeStore, RecordCollector]:
    store = store or FakeStore()
    registrar = registrar or RecordCollector()
    manager = EvidenceManager(
        policy=policy,
        store=store,  # type: ignore[arg-type]
        registrar=registrar,
        encoder_queue_maxsize=encoder_queue_maxsize,
        rotation=rotation,
    )
    if buffer is not None:
        manager.bind_buffer(buffer)
    return manager, store, registrar


def test_pre_event_window_uses_only_frames_inside_the_cutoff() -> None:
    old, recent = Buffered(FakeImage(), 3.0, None), Buffered(FakeImage(), 7.0, None)  # type: ignore[arg-type]
    manager, store, records = _manager(buffer=FakeBuffer([old, recent]))

    manager.handle_transition(make_transition(), monotonic=10.0)

    assert wait_until(lambda: len(records.all()) == 2)
    assert len(store.clips) == 1
    assert store.clips[0]["frames"] == [recent.image]
    assert store.snapshots[0]["image"] is recent.image


def test_post_event_frames_are_collected_until_the_deadline() -> None:
    policy = EvidencePolicy(post_event_seconds=5.0, clip_fps=1.0)
    manager, store, records = _manager(policy=policy, buffer=FakeBuffer([]))
    manager.handle_transition(make_transition(), monotonic=10.0)

    first = Buffered(FakeImage(), 11.0, None)
    second = Buffered(FakeImage(), 12.0, None)
    late = Buffered(FakeImage(), 15.5, None)
    manager.on_frame(first, 11.0)
    manager.on_frame(second, 12.0)
    manager.on_frame(late, 15.5)

    assert wait_until(lambda: len(records.all()) == 2)
    assert store.clips[0]["frames"] == [first.image, second.image, late.image]
    assert store.snapshots[0]["image"] is first.image
    assert manager.active_captures == 0


def test_duplicate_transitions_open_only_one_capture() -> None:
    manager, _store, records = _manager()
    transition = make_transition("same-event")

    manager.handle_transition(transition, monotonic=1.0)
    manager.handle_transition(transition, monotonic=2.0)

    assert wait_until(lambda: len(records.all()) == 2)
    assert manager.counters()["capture_started"] == 1


def test_missing_frames_are_recorded_as_explicit_failures() -> None:
    manager, _store, records = _manager(buffer=FakeBuffer([]))

    manager.handle_transition(make_transition(), monotonic=1.0)

    assert wait_until(lambda: len(records.all()) == 2)
    assert {record.media_type for record in records.all()} == {"snapshot", "clip"}
    assert all(record.status == "failed" for record in records.all())
    assert all(record.error == "no_frames" for record in records.all())


def test_sideways_camera_evidence_is_rotated_upright() -> None:
    """D-72/D-73: recorded snapshot/clip are written in the camera rotation, not raw."""
    numpy = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    image = numpy.zeros((4, 6, 3), dtype="uint8")  # source frame: 6 wide x 4 tall
    manager, store, records = _manager(
        buffer=FakeBuffer([Buffered(image, 7.0, None)]),  # type: ignore[arg-type]
        rotation=90,
    )

    manager.handle_transition(make_transition(), monotonic=10.0)

    assert wait_until(lambda: len(records.all()) == 2)
    # A 90-degree clockwise rotation transposes the frame: (h, w) -> (w, h).
    assert store.snapshots[0]["image"].shape == (6, 4, 3)
    assert store.clips[0]["frames"][0].shape == (6, 4, 3)
    # The buffered original is never mutated in place.
    assert image.shape == (4, 6, 3)


def test_encoder_queue_overflow_records_a_failure_instead_of_growing() -> None:
    released = threading.Event()
    started = threading.Event()

    class BlockingStore(FakeStore):
        def save_snapshot(self, **kwargs):
            started.set()
            return super().save_snapshot(**kwargs)

        def save_clip(self, **kwargs):
            started.set()
            return super().save_clip(**kwargs)

    store = BlockingStore(block=released)
    manager, _store, records = _manager(
        store=store,
        encoder_queue_maxsize=1,
        buffer=FakeBuffer([Buffered(FakeImage(), 0.9, None)]),  # type: ignore[arg-type]
    )
    manager.start()

    manager.handle_transition(make_transition("blocking"), monotonic=1.0)
    assert wait_until(started.is_set)

    manager.handle_transition(make_transition("queued"), monotonic=2.0)
    assert wait_until(lambda: manager._jobs.qsize() == 1)  # noqa: SLF001 - deterministic check

    manager.handle_transition(make_transition("overflow"), monotonic=3.0)
    overflow = [record for record in records.all() if record.event_id == "overflow"]
    assert len(overflow) == 2
    assert all(record.status == "failed" for record in overflow)
    assert all(record.error == "encoder_overloaded" for record in overflow)
    assert manager.counters()["dropped_jobs"] == 1

    released.set()
    manager.shutdown()


def test_active_capture_limit_finalises_the_oldest_early() -> None:
    policy = EvidencePolicy(post_event_seconds=100.0, max_active_events=1)
    manager, _store, records = _manager(policy=policy)

    manager.handle_transition(make_transition("first"), monotonic=1.0)
    manager.handle_transition(make_transition("second"), monotonic=2.0)

    assert manager.active_captures == 1
    assert manager.counters()["dropped_collections"] == 1
    assert wait_until(lambda: {record.event_id for record in records.all()} == {"first"})

    manager.on_stream_end(3.0)
    assert wait_until(lambda: {record.event_id for record in records.all()} == {"first", "second"})


def test_reset_and_stream_end_finalise_open_captures() -> None:
    policy = EvidencePolicy(post_event_seconds=100.0)
    manager, _store, records = _manager(policy=policy)

    manager.handle_transition(make_transition("a"), monotonic=1.0)
    manager.reset()
    manager.handle_transition(make_transition("b"), monotonic=2.0)
    manager.on_stream_end(3.0)

    assert manager.active_captures == 0
    assert wait_until(lambda: len(records.all()) == 4)


def test_shutdown_finalises_active_captures() -> None:
    policy = EvidencePolicy(post_event_seconds=100.0)
    manager, _store, records = _manager(policy=policy)
    manager.handle_transition(make_transition("late"), monotonic=1.0)

    manager.shutdown()

    assert manager.active_captures == 0
    assert len(records.all()) == 2


def test_disabled_policy_captures_nothing() -> None:
    manager, _store, records = _manager(policy=EvidencePolicy(enabled=False))

    manager.handle_transition(make_transition(), monotonic=1.0)
    manager.on_frame(Buffered(FakeImage(), 2.0, None), 2.0)  # type: ignore[arg-type]

    time.sleep(0.05)
    assert records.all() == []
    assert manager.active_captures == 0


def test_capture_bookkeeping_does_not_block_the_frame_caller() -> None:
    """FR-37: a busy encoder must not block the thread that feeds evidence."""
    released = threading.Event()
    started = threading.Event()

    class SignallingStore(FakeStore):
        def save_snapshot(self, **kwargs):
            started.set()
            return super().save_snapshot(**kwargs)

    manager, _store, _records = _manager(
        store=SignallingStore(block=released), buffer=FakeBuffer([Buffered(FakeImage(), 0.9, None)])
    )
    manager.start()

    # First capture occupies the single encoder thread until ``released`` is set.
    manager.handle_transition(make_transition("first"), monotonic=1.0)
    assert wait_until(started.is_set)

    # While the encoder is blocked, producer-side bookkeeping must return promptly.
    before = time.monotonic()
    manager.handle_transition(make_transition("second"), monotonic=2.0)
    manager.on_frame(Buffered(FakeImage(), 2.0, None), 2.0)  # type: ignore[arg-type]
    elapsed = time.monotonic() - before

    released.set()
    manager.shutdown()
    assert elapsed < 0.5, f"frame-thread evidence bookkeeping blocked for {elapsed:.3f}s"
