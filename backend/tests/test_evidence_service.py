"""Evidence registration, path confinement, and retention (Phase 6; FR-38/41/42)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

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


def _write_file(evidence_dir, relative: str, size: int) -> None:
    path = evidence_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"a" * size)


def _add_evidence(
    db: Session,
    event: Event,
    *,
    media_type: str = "snapshot",
    captured_at: datetime = NOW,
    size: int = 100,
    status: str = EvidenceStatus.AVAILABLE.value,
    retention: str = RetentionStatus.RETAINED.value,
    relative_path: str | None = "camera-1/f.jpg",
) -> Evidence:
    row = Evidence(
        event_id=event.id,
        media_type=media_type,
        captured_at=captured_at,
        status=status,
        retention_status=retention,
        relative_path=relative_path,
        file_size_bytes=size,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --- path confinement -----------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    ["/etc/passwd", "../secrets", "camera-1/../../etc/passwd", "..", ""],
)
def test_unsafe_paths_are_rejected(evidence_dir, path: str) -> None:
    assert evidence_service.is_safe_relative_path(path) is False
    with pytest.raises(evidence_service.EvidencePathError):
        evidence_service.resolve_evidence_path(path)


def test_safe_path_resolves_inside_root(evidence_dir) -> None:
    resolved = evidence_service.resolve_evidence_path("camera-1/2026/10/29/a.jpg")
    assert str(resolved).startswith(str(evidence_dir.resolve()))


# --- registration ---------------------------------------------------------------


def test_register_available_verifies_file(db_session_factory, camera, evidence_dir) -> None:
    db = db_session_factory()
    try:
        event = _event(db, camera.id)
        _write_file(evidence_dir, "camera-1/a.jpg", 42)
        result = evidence_service.register_evidence(
            db,
            InternalEvidenceSubmission(
                event_id=event.event_id,
                media_type="snapshot",
                status="available",
                relative_path="camera-1/a.jpg",
                captured_at=NOW,
            ),
        )
        assert result.evidence.status == EvidenceStatus.AVAILABLE.value
        assert result.evidence.file_size_bytes == 42
    finally:
        db.close()


def test_register_available_without_file_becomes_failed(
    db_session_factory, camera, evidence_dir
) -> None:
    db = db_session_factory()
    try:
        event = _event(db, camera.id)
        result = evidence_service.register_evidence(
            db,
            InternalEvidenceSubmission(
                event_id=event.event_id,
                media_type="clip",
                status="available",
                relative_path="camera-1/missing.mp4",
                captured_at=NOW,
            ),
        )
        assert result.evidence.status == EvidenceStatus.FAILED.value
        assert result.evidence.error == "file_not_found"
    finally:
        db.close()


def test_register_is_idempotent_per_media_type(db_session_factory, camera, evidence_dir) -> None:
    db = db_session_factory()
    try:
        event = _event(db, camera.id)
        _write_file(evidence_dir, "camera-1/a.jpg", 10)
        first = evidence_service.register_evidence(
            db,
            InternalEvidenceSubmission(
                event_id=event.event_id,
                media_type="snapshot",
                status="available",
                relative_path="camera-1/a.jpg",
                captured_at=NOW,
            ),
        )
        second = evidence_service.register_evidence(
            db,
            InternalEvidenceSubmission(
                event_id=event.event_id,
                media_type="snapshot",
                status="available",
                relative_path="camera-1/a.jpg",
                captured_at=NOW,
            ),
        )
        assert first.evidence.id == second.evidence.id
        assert len(evidence_repo.list_by_event(db, event.id)) == 1
    finally:
        db.close()


def test_register_unknown_event_raises(db_session_factory, camera, evidence_dir) -> None:
    db = db_session_factory()
    try:
        with pytest.raises(evidence_service.UnknownEvent):
            evidence_service.register_evidence(
                db,
                InternalEvidenceSubmission(
                    event_id="nope",
                    media_type="snapshot",
                    status="failed",
                    error="encode_failed",
                    captured_at=NOW,
                ),
            )
    finally:
        db.close()


# --- retention ------------------------------------------------------------------


def test_retention_deletes_expired_evidence(db_session_factory, camera, evidence_dir) -> None:
    db = db_session_factory()
    try:
        event = _event(db, camera.id)
        old = _add_evidence(
            db, event, captured_at=NOW - timedelta(days=40), relative_path="camera-1/old.jpg"
        )
        fresh = _add_evidence(
            db,
            event,
            media_type="clip",
            captured_at=NOW - timedelta(days=1),
            relative_path="camera-1/new.mp4",
        )
        report = evidence_service.run_retention(db, now=NOW)
        assert report.deleted == 1
        assert old.retention_status == RetentionStatus.DELETED.value
        assert fresh.retention_status == RetentionStatus.RETAINED.value
    finally:
        db.close()


def test_retention_respects_storage_cap_oldest_first(
    db_session_factory, camera, evidence_dir
) -> None:
    db = db_session_factory()
    try:
        e1 = _event(db, camera.id, "evt-1")
        e2 = _event(db, camera.id, "evt-2")
        e3 = _event(db, camera.id, "evt-3")
        oldest = _add_evidence(
            db, e1, captured_at=NOW - timedelta(days=3), size=600, relative_path="camera-1/a"
        )
        middle = _add_evidence(
            db,
            e2,
            media_type="clip",
            captured_at=NOW - timedelta(days=2),
            size=600,
            relative_path="camera-1/b",
        )
        newest = _add_evidence(
            db,
            e3,
            media_type="snapshot",
            captured_at=NOW - timedelta(days=1),
            size=600,
            relative_path="camera-1/c",
        )
        report = evidence_service.run_retention(db, now=NOW, storage_limit_bytes=700)
        assert oldest.retention_status == RetentionStatus.DELETED.value
        assert middle.retention_status == RetentionStatus.DELETED.value
        assert newest.retention_status == RetentionStatus.RETAINED.value
        assert report.deleted == 2
    finally:
        db.close()


def test_retention_never_deletes_protected_evidence(
    db_session_factory, camera, evidence_dir
) -> None:
    db = db_session_factory()
    try:
        event = _event(db, camera.id)
        protected = _add_evidence(
            db,
            event,
            captured_at=NOW - timedelta(days=90),
            retention=RetentionStatus.PROTECTED.value,
            relative_path="camera-1/p.jpg",
        )
        report = evidence_service.run_retention(db, now=NOW)
        assert report.deleted == 0
        assert report.protected_count == 1
        assert protected.retention_status == RetentionStatus.PROTECTED.value
    finally:
        db.close()


def test_retention_reports_when_all_candidates_are_protected(
    db_session_factory, camera, evidence_dir
) -> None:
    db = db_session_factory()
    try:
        event = _event(db, camera.id)
        _add_evidence(
            db,
            event,
            captured_at=NOW,
            size=5000,
            retention=RetentionStatus.PROTECTED.value,
            relative_path="camera-1/p.jpg",
        )
        report = evidence_service.run_retention(db, now=NOW, storage_limit_bytes=100)
        assert report.blocked_by_protection is True
        assert report.deleted == 0
    finally:
        db.close()


def test_retention_deletes_the_file_and_keeps_the_row(
    db_session_factory, camera, evidence_dir
) -> None:
    db = db_session_factory()
    try:
        event = _event(db, camera.id)
        relative = "camera-1/gone.jpg"
        _write_file(evidence_dir, relative, 20)
        row = _add_evidence(db, event, captured_at=NOW - timedelta(days=40), relative_path=relative)
        evidence_service.run_retention(db, now=NOW)
        assert not (evidence_dir / relative).exists()
        assert row.retention_status == RetentionStatus.DELETED.value
        assert row.deleted_at is not None
    finally:
        db.close()


def test_protect_and_release(db_session_factory, camera, evidence_dir) -> None:
    db = db_session_factory()
    try:
        event = _event(db, camera.id)
        row = _add_evidence(db, event, relative_path="camera-1/x.jpg")
        evidence_service.protect_evidence(db, row)
        assert row.retention_status == RetentionStatus.PROTECTED.value
        evidence_service.release_evidence(db, row)
        assert row.retention_status == RetentionStatus.RETAINED.value
    finally:
        db.close()
