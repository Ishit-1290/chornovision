"""Bounded, durable event/evidence handoff tests (Phase 6; FR-40, D-12)."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from vision.event_handoff import EventHandoff
from vision.evidence.store import EvidenceRecord
from vision.internal_client import InternalClientError, PermanentInternalError

from .evidence_helpers import at, make_transition
from .fakes import wait_until


class FakeClient:
    """Records submissions; scripted outcomes may raise before recording."""

    def __init__(self, outcomes: list[BaseException] | None = None) -> None:
        self._lock = threading.Lock()
        self._outcomes = list(outcomes or [])
        self._gate: threading.Event | None = None
        self.started = threading.Event()
        self.events: list[dict[str, Any]] = []
        self.evidence: list[tuple[str, dict[str, Any]]] = []
        self.calls: list[str] = []

    def block_on_first_call(self) -> threading.Event:
        self._gate = threading.Event()
        return self._gate

    def _enter(self, kind: str) -> None:
        with self._lock:
            self.calls.append(kind)
            outcome = self._outcomes.pop(0) if self._outcomes else None
        if kind == "event":
            self.started.set()
            gate = self._gate
            if gate is not None:
                gate.wait(5.0)
        if isinstance(outcome, BaseException):
            raise outcome

    def submit_event(self, payload: dict[str, Any]) -> None:
        self._enter("event")
        with self._lock:
            self.events.append(payload)

    def register_evidence(self, event_id: str, payload: dict[str, Any]) -> None:
        self._enter("evidence")
        with self._lock:
            self.evidence.append((event_id, payload))


def _record(event_id: str = "event-1") -> EvidenceRecord:
    return EvidenceRecord(
        event_id=event_id,
        media_type="snapshot",
        status="available",
        relative_path="camera-1/2026/01/01/event-1-snapshot.jpg",
        file_size_bytes=12,
        duration_seconds=None,
        captured_at=at(0.0),
    )


def _handoff(
    client: FakeClient,
    spool: Path,
    *,
    queue_maxsize: int = 100,
    spool_max_bytes: int = 1_000_000,
    max_attempts: int = 3,
) -> EventHandoff:
    return EventHandoff(
        client=client,  # type: ignore[arg-type]
        camera_id=1,
        queue_maxsize=queue_maxsize,
        spool_dir=spool,
        spool_max_bytes=spool_max_bytes,
        max_attempts=max_attempts,
        retry_backoff_seconds=0.0,
    )


def test_events_and_evidence_are_delivered(tmp_path: Path) -> None:
    client = FakeClient()
    handoff = _handoff(client, tmp_path)

    handoff.enqueue_event(make_transition("event-1"))
    handoff.enqueue_evidence(_record("event-1"))

    assert handoff.flush(timeout=3.0)
    assert client.events[0]["event"]["event_id"] == "event-1"
    assert client.events[0]["action"] == "opened"
    assert client.evidence[0][0] == "event-1"
    assert client.evidence[0][1]["media_type"] == "snapshot"
    assert handoff.counters()["delivered"] == 2
    handoff.shutdown()


def test_transient_failure_is_retried(tmp_path: Path) -> None:
    client = FakeClient([InternalClientError("temporary")])
    handoff = _handoff(client, tmp_path, max_attempts=3)

    handoff.enqueue_event(make_transition())

    assert wait_until(lambda: handoff.counters()["delivered"] == 1)
    assert len(client.calls) == 2
    assert handoff.counters()["failed"] == 0
    handoff.shutdown()


def test_permanent_failure_is_discarded_without_retry(tmp_path: Path) -> None:
    client = FakeClient([PermanentInternalError("rejected")])
    handoff = _handoff(client, tmp_path, max_attempts=5)

    handoff.enqueue_event(make_transition())

    assert wait_until(lambda: handoff.counters()["failed"] == 1)
    assert len(client.calls) == 1
    handoff.shutdown()


def test_retries_are_bounded(tmp_path: Path) -> None:
    client = FakeClient([InternalClientError("down"), InternalClientError("down")])
    handoff = _handoff(client, tmp_path, max_attempts=2)

    handoff.enqueue_event(make_transition())

    assert wait_until(lambda: handoff.counters()["failed"] == 1)
    assert len(client.calls) == 2
    handoff.shutdown()


def test_queue_overflow_spills_to_disk_then_delivers(tmp_path: Path) -> None:
    client = FakeClient()
    gate = client.block_on_first_call()
    handoff = _handoff(client, tmp_path, queue_maxsize=1)

    handoff.enqueue_event(make_transition("first"))
    assert wait_until(client.started.is_set)
    handoff.enqueue_event(make_transition("second"))  # fills the in-memory queue
    handoff.enqueue_event(make_transition("third"))  # spills to the durable spool

    assert handoff.counters()["spooled"] == 1
    assert len(list(tmp_path.glob("handoff-*.json"))) == 1

    gate.set()
    assert handoff.flush(timeout=5.0)
    assert [event["event"]["event_id"] for event in client.events] == [
        "first",
        "second",
        "third",
    ]
    assert list(tmp_path.glob("handoff-*.json")) == []
    handoff.shutdown()


def test_full_spool_drops_explicitly_at_the_hard_limit(tmp_path: Path) -> None:
    client = FakeClient()
    gate = client.block_on_first_call()
    handoff = _handoff(client, tmp_path, queue_maxsize=1, spool_max_bytes=1)

    handoff.enqueue_event(make_transition("first"))
    assert wait_until(client.started.is_set)
    handoff.enqueue_event(make_transition("second"))
    handoff.enqueue_event(make_transition("third"))

    assert handoff.counters()["dropped"] == 1
    assert list(tmp_path.glob("handoff-*.json")) == []

    gate.set()
    assert handoff.flush(timeout=5.0)
    handoff.shutdown()


def test_spooled_items_are_recovered_by_a_new_handoff(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    spooled = tmp_path / "handoff-1-1-1.json"
    spooled.write_text(
        json.dumps(
            {
                "kind": "event",
                "payload": {
                    "action": "opened",
                    "event": make_transition("recovered").event.model_dump(mode="json"),
                },
            }
        )
    )
    client = FakeClient()
    handoff = _handoff(client, tmp_path)

    handoff.start()

    assert wait_until(lambda: len(client.events) == 1)
    assert client.events[0]["event"]["event_id"] == "recovered"
    assert not spooled.exists()
    handoff.shutdown()


def test_corrupt_spool_file_is_discarded(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "handoff-1-bad.json").write_text("not-json")
    client = FakeClient()
    handoff = _handoff(client, tmp_path)

    handoff.start()

    assert wait_until(lambda: handoff.counters()["failed"] == 1)
    assert list(tmp_path.glob("handoff-*.json")) == []
    handoff.shutdown()


def test_a_camera_never_delivers_another_cameras_spooled_items(tmp_path: Path) -> None:
    """Phase 8 isolation: shared spool directory, per-camera ownership of files."""
    tmp_path.mkdir(exist_ok=True)
    # A spooled item that belongs to camera 2.
    (tmp_path / "handoff-2-1-1.json").write_text(
        json.dumps(
            {
                "kind": "event",
                "payload": {
                    "action": "opened",
                    "event": make_transition("belongs-to-2").event.model_dump(mode="json"),
                },
            }
        )
    )
    client = FakeClient()
    handoff = EventHandoff(
        client=client,  # type: ignore[arg-type]
        camera_id=1,
        queue_maxsize=100,
        spool_dir=tmp_path,
        spool_max_bytes=1_000_000,
    )

    handoff.start()

    # Camera 1's deliverer must not pick up camera 2's spool file.
    assert not wait_until(lambda: len(client.events) >= 1, timeout=0.5)
    assert (tmp_path / "handoff-2-1-1.json").exists()
    handoff.shutdown()


def test_flush_reports_timeout_when_delivery_is_blocked(tmp_path: Path) -> None:
    client = FakeClient()
    gate = client.block_on_first_call()
    handoff = _handoff(client, tmp_path)

    handoff.enqueue_event(make_transition())
    assert wait_until(client.started.is_set)
    assert handoff.flush(timeout=0.05) is False

    gate.set()
    assert handoff.flush(timeout=3.0)
    handoff.shutdown()
