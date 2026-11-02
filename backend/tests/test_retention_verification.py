"""Phase 9 evidence-retention verification (G §16, W §13 M8; FR-41/FR-42).

End-to-end checks of the retention policy against a disposable SQLite database and a
per-test temporary evidence directory (the ``evidence_dir`` fixture). The real application
database and evidence directory are never touched.

Verified here:

* the time window expires only evidence older than the cutoff (strictly);
* the storage cap evicts **oldest-eligible-first**;
* evidence pinned for active review is never evicted, and a cap that cannot be met without
  evicting protected evidence is reported via ``blocked_by_protection`` rather than forced;
* eviction unlinks the file but keeps the row (traceability) and updates its status;
* retention is **not** a capture side effect while ``EVIDENCE_RETENTION_ON_REGISTER=false``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.config import clear_settings_cache, get_settings
from app.models.event import Event
from app.models.evidence import Evidence, EvidenceStatus, RetentionStatus
from app.repositories import evidence as evidence_repo
from app.schemas.internal import InternalEvidenceSubmission
from app.services import camera_service, evidence_service

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


@pytest.fixture
def camera(db_session_factory, admin_env):
    db = db_session_factory()
    try:
        return camera_service.create_camera(
            db, name="front-door", stream_reference="rtsp://192.168.1.10:554/s1"
        )
    finally:
        db.close()


def _event(db: Session, camera_id: int, event_id: str = "evt-1") -> Event:
    event = Event(
        event_id=event_id,
        camera_id=camera_id,
        event_type="person_entering",
        start_time=NOW,
        trigger_time=NOW,
        last_updated_at=NOW,
        status="active",
        severity="info",
        certainty="medium",
        message="x",
        attributes={},
        evidence_refs=[],
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def _add_evidence(
    db: Session,
    camera_id: int,
    *,
    relative: str,
    captured_at: datetime,
    size: int,
    retention: str = RetentionStatus.RETAINED.value,
    event: Event | None = None,
) -> Evidence:
    if event is None:
        # A distinct event per item keeps the (event_id, media_type) uniqueness intact.
        _add_evidence._counter += 1  # type: ignore[attr-defined]
        event = _event(db, camera_id, event_id=f"evt-{_add_evidence._counter}")  # type: ignore[attr-defined]
    row = Evidence(
        event_id=event.id,
        media_type="snapshot",
        captured_at=captured_at,
        status=EvidenceStatus.AVAILABLE.value,
        retention_status=retention,
        relative_path=relative,
        file_size_bytes=size,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


_add_evidence._counter = 100  # type: ignore[attr-defined]


def _write(evidence_dir, relative: str, size: int) -> None:
    path = evidence_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"a" * size)


# --------------------------------------------------------------------------------------
# Retention is explicit, not a capture side effect
# --------------------------------------------------------------------------------------


def test_retention_does_not_run_on_register_when_disabled(
    db_session_factory, camera, evidence_dir
) -> None:
    assert get_settings().evidence_retention_on_register is False
    db = db_session_factory()
    try:
        # Two long-expired items that a capture-time retention run would delete.
        stale_a = _add_evidence(
            db, camera.id, relative="c/a.jpg", captured_at=NOW - timedelta(days=100), size=100
        )
        stale_b = _add_evidence(
            db, camera.id, relative="c/b.jpg", captured_at=NOW - timedelta(days=100), size=100
        )
        before = len(evidence_repo.list_retained(db))
        # Registering new evidence must not trigger retention while the flag is off.
        _add_evidence(db, camera.id, relative="c/c.jpg", captured_at=NOW, size=100)
        after = len(evidence_repo.list_retained(db))
        assert after == before + 1
        assert (
            evidence_repo.get_by_id(db, stale_a.id).retention_status
            == RetentionStatus.RETAINED.value
        )
        assert (
            evidence_repo.get_by_id(db, stale_b.id).retention_status
            == RetentionStatus.RETAINED.value
        )
    finally:
        db.close()


def test_retention_runs_on_register_when_explicitly_enabled(
    db_session_factory, camera, evidence_dir, monkeypatch
) -> None:
    monkeypatch.setenv("EVIDENCE_RETENTION_ON_REGISTER", "true")
    clear_settings_cache()
    try:
        assert get_settings().evidence_retention_on_register is True
        db = db_session_factory()
        try:
            event = _event(db, camera.id)
            _write(evidence_dir, "c/old.jpg", 10)
            stale = _add_evidence(
                db, camera.id, relative="c/old.jpg", captured_at=NOW - timedelta(days=100), size=10
            )
            # A *new* registration (distinct media type) triggers opportunistic retention,
            # which sweeps the already-expired snapshot.
            _write(evidence_dir, "c/new.mp4", 10)
            submission = InternalEvidenceSubmission(
                event_id=event.event_id,
                media_type="clip",
                status="available",
                relative_path="c/new.mp4",
                captured_at=NOW,
            )
            evidence_service.register_evidence(db, submission)

            stored = evidence_repo.get_by_id(db, stale.id)
            assert stored.retention_status == RetentionStatus.DELETED.value
            assert not (evidence_dir / "c/old.jpg").exists()
        finally:
            db.close()
    finally:
        clear_settings_cache()


# --------------------------------------------------------------------------------------
# Time window
# --------------------------------------------------------------------------------------


def test_time_window_expires_only_older_evidence(db_session_factory, camera, evidence_dir) -> None:
    db = db_session_factory()
    try:
        _write(evidence_dir, "c/old.jpg", 10)
        _write(evidence_dir, "c/edge.jpg", 10)
        _write(evidence_dir, "c/new.jpg", 10)
        old = _add_evidence(
            db, camera.id, relative="c/old.jpg", captured_at=NOW - timedelta(days=31), size=10
        )
        edge = _add_evidence(
            db, camera.id, relative="c/edge.jpg", captured_at=NOW - timedelta(days=30), size=10
        )
        new = _add_evidence(
            db, camera.id, relative="c/new.jpg", captured_at=NOW - timedelta(days=1), size=10
        )

        report = evidence_service.run_retention(db, now=NOW, retention_days=30)

        assert report.deleted == 1
        assert report.deleted_ids == [old.id]
        assert not (evidence_dir / "c/old.jpg").exists()
        # Exactly at the cutoff is retained (strictly-older comparison).
        assert (
            evidence_repo.get_by_id(db, edge.id).retention_status == RetentionStatus.RETAINED.value
        )
        assert (
            evidence_repo.get_by_id(db, new.id).retention_status == RetentionStatus.RETAINED.value
        )
        assert (evidence_dir / "c/edge.jpg").exists()
    finally:
        db.close()


# --------------------------------------------------------------------------------------
# Storage cap
# --------------------------------------------------------------------------------------


def test_storage_cap_evicts_oldest_first(db_session_factory, camera, evidence_dir) -> None:
    db = db_session_factory()
    try:
        for name in ("a", "b", "c"):
            _write(evidence_dir, f"c/{name}.jpg", 100)
        oldest = _add_evidence(
            db, camera.id, relative="c/a.jpg", captured_at=NOW - timedelta(hours=3), size=100
        )
        middle = _add_evidence(
            db, camera.id, relative="c/b.jpg", captured_at=NOW - timedelta(hours=2), size=100
        )
        newest = _add_evidence(
            db, camera.id, relative="c/c.jpg", captured_at=NOW - timedelta(hours=1), size=100
        )

        # Cap of 250 bytes over three 100-byte items evicts exactly the oldest one.
        report = evidence_service.run_retention(
            db, now=NOW, retention_days=3650, storage_limit_bytes=250
        )

        assert report.deleted == 1
        assert report.deleted_ids == [oldest.id]
        assert report.bytes_freed == 100
        assert report.remaining_bytes == 200
        assert not (evidence_dir / "c/a.jpg").exists()
        assert (evidence_dir / "c/b.jpg").exists()
        assert (evidence_dir / "c/c.jpg").exists()
        assert (
            evidence_repo.get_by_id(db, middle.id).retention_status
            == RetentionStatus.RETAINED.value
        )
        assert (
            evidence_repo.get_by_id(db, newest.id).retention_status
            == RetentionStatus.RETAINED.value
        )
    finally:
        db.close()


def test_protected_evidence_is_never_evicted_by_cap(
    db_session_factory, camera, evidence_dir
) -> None:
    db = db_session_factory()
    try:
        for name in ("keep", "drop"):
            _write(evidence_dir, f"c/{name}.jpg", 100)
        protected = _add_evidence(
            db,
            camera.id,
            relative="c/keep.jpg",
            captured_at=NOW - timedelta(hours=3),
            size=100,
            retention=RetentionStatus.PROTECTED.value,
        )
        oldest_eligible = _add_evidence(
            db, camera.id, relative="c/drop.jpg", captured_at=NOW - timedelta(hours=2), size=100
        )

        # Even though the protected item is older, the cap evicts the oldest *eligible* item.
        report = evidence_service.run_retention(
            db, now=NOW, retention_days=3650, storage_limit_bytes=50
        )

        assert report.deleted == 1
        assert report.deleted_ids == [oldest_eligible.id]
        assert report.protected_count == 1
        assert (
            evidence_repo.get_by_id(db, protected.id).retention_status
            == RetentionStatus.PROTECTED.value
        )
        assert (evidence_dir / "c/keep.jpg").exists()
        assert not (evidence_dir / "c/drop.jpg").exists()
    finally:
        db.close()


def test_cap_that_cannot_be_met_under_protection_is_blocked(
    db_session_factory, camera, evidence_dir
) -> None:
    db = db_session_factory()
    try:
        _write(evidence_dir, "c/keep.jpg", 500)
        protected = _add_evidence(
            db,
            camera.id,
            relative="c/keep.jpg",
            captured_at=NOW - timedelta(hours=3),
            size=500,
            retention=RetentionStatus.PROTECTED.value,
        )

        report = evidence_service.run_retention(
            db, now=NOW, retention_days=3650, storage_limit_bytes=100
        )

        assert report.deleted == 0
        assert report.blocked_by_protection is True
        assert (
            evidence_repo.get_by_id(db, protected.id).retention_status
            == RetentionStatus.PROTECTED.value
        )
        assert (evidence_dir / "c/keep.jpg").exists()
    finally:
        db.close()


# --------------------------------------------------------------------------------------
# Row/file semantics and idempotence
# --------------------------------------------------------------------------------------


def test_eviction_unlinks_file_but_keeps_row(db_session_factory, camera, evidence_dir) -> None:
    db = db_session_factory()
    try:
        _write(evidence_dir, "c/old.jpg", 42)
        row = _add_evidence(
            db, camera.id, relative="c/old.jpg", captured_at=NOW - timedelta(days=40), size=42
        )

        report = evidence_service.run_retention(db, now=NOW, retention_days=30)
        assert report.deleted == 1

        stored = evidence_repo.get_by_id(db, row.id)
        assert stored is not None  # the row survives for traceability
        assert stored.retention_status == RetentionStatus.DELETED.value
        assert stored.deleted_at is not None
        assert not (evidence_dir / "c/old.jpg").exists()
        # Deleted rows are excluded from the live accounting set.
        assert all(item.id != row.id for item in evidence_repo.list_retained(db))
    finally:
        db.close()


def test_retention_is_idempotent(db_session_factory, camera, evidence_dir) -> None:
    db = db_session_factory()
    try:
        _write(evidence_dir, "c/old.jpg", 10)
        _add_evidence(
            db, camera.id, relative="c/old.jpg", captured_at=NOW - timedelta(days=40), size=10
        )

        first = evidence_service.run_retention(db, now=NOW, retention_days=30)
        second = evidence_service.run_retention(db, now=NOW, retention_days=30)

        assert first.deleted == 1
        assert second.deleted == 0
        assert second.bytes_freed == 0
    finally:
        db.close()
