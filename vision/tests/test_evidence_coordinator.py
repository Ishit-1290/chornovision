"""Evidence/event coordinator wiring tests (Phase 6; FR-36, FR-40)."""

from __future__ import annotations

from vision.evidence.coordinator import EvidenceCoordinator

from .evidence_helpers import make_transition


class FakeManager:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.buffer = None
        self.counters_value = {"capture_started": 2, "evidence_registered": 1}
        self.active = 3

    def bind_buffer(self, buffer) -> None:
        self.buffer = buffer
        self.calls.append(("bind", id(buffer)))

    def handle_transition(self, transition, monotonic: float) -> None:
        self.calls.append(("transition", transition.event.event_id, monotonic))

    def on_frame(self, frame, monotonic: float) -> None:
        self.calls.append(("frame", frame, monotonic))

    def on_stream_end(self, monotonic: float) -> None:
        self.calls.append(("end", monotonic))

    def reset(self) -> None:
        self.calls.append(("reset",))

    def start(self) -> None:
        self.calls.append(("start",))

    def shutdown(self, timeout: float = 5.0) -> None:
        self.calls.append(("shutdown", timeout))

    def counters(self) -> dict[str, int]:
        return dict(self.counters_value)

    @property
    def active_captures(self) -> int:
        return self.active


class FakeHandoff:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.counters_value = {"enqueued": 4, "delivered": 3}

    def enqueue_event(self, transition) -> None:
        self.calls.append(("event", transition.event.event_id))

    def start(self) -> None:
        self.calls.append(("start",))

    def shutdown(self, timeout: float = 5.0) -> None:
        self.calls.append(("shutdown", timeout))

    def counters(self) -> dict[str, int]:
        return dict(self.counters_value)


def _coordinator(clock=lambda: 10.0) -> tuple[EvidenceCoordinator, FakeManager, FakeHandoff]:
    manager, handoff = FakeManager(), FakeHandoff()
    coordinator = EvidenceCoordinator(
        camera_id=1,
        manager=manager,  # type: ignore[arg-type]
        handoff=handoff,  # type: ignore[arg-type]
        clock=clock,
    )
    return coordinator, manager, handoff


def test_publish_enqueues_the_event_before_opening_capture() -> None:
    coordinator, manager, handoff = _coordinator()

    coordinator.publish(make_transition("event-9"))

    assert handoff.calls == [("event", "event-9")]
    assert manager.calls == [("transition", "event-9", 10.0)]
    assert handoff.calls[0][0] == "event"


def test_frame_and_session_callbacks_use_the_shared_clock() -> None:
    coordinator, manager, _handoff = _coordinator(clock=lambda: 42.0)
    frame = object()

    coordinator.bind_buffer("buffer")  # type: ignore[arg-type]
    coordinator.on_frame(frame)
    coordinator.on_stream_end()
    coordinator.reset()

    assert manager.calls == [
        ("bind", id("buffer")),
        ("frame", frame, 42.0),
        ("end", 42.0),
        ("reset",),
    ]


def test_explicit_monotonic_overrides_the_clock() -> None:
    coordinator, manager, _handoff = _coordinator(clock=lambda: 1.0)
    frame = object()

    coordinator.on_frame(frame, 5.0)
    coordinator.on_stream_end(6.0)

    assert ("frame", frame, 5.0) in manager.calls
    assert ("end", 6.0) in manager.calls


def test_start_and_shutdown_order_flushes_evidence_before_delivery() -> None:
    coordinator, manager, handoff = _coordinator()

    coordinator.start()
    coordinator.shutdown(timeout=2.0)

    assert manager.calls == [("start",), ("shutdown", 2.0)]
    assert handoff.calls == [("start",), ("shutdown", 2.0)]
    # Manager shutdown (which finalises/encodes evidence) must precede handoff shutdown.
    assert manager.calls[-1][0] == "shutdown"
    assert handoff.calls[-1][0] == "shutdown"


def test_counters_are_namespaced() -> None:
    coordinator, _manager, _handoff = _coordinator()

    counters = coordinator.counters()

    assert counters["evidence_capture_started"] == 2
    assert counters["evidence_registered"] == 1
    assert counters["evidence_active_captures"] == 3
    assert counters["handoff_enqueued"] == 4
    assert counters["handoff_delivered"] == 3
