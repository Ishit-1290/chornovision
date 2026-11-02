"""Reviewer evidence protection and its effect on retention (Phase 7; FR-42, D-43)."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.internal import INTERNAL_TOKEN_HEADER
from app.models.evidence import RetentionStatus
from app.repositories import evidence as evidence_repo
from app.services import evidence_service

from . import event_builders as eb

STREAM = "rtsp://192.168.1.10:554/stream1"
EVENT_ID = "66666666-6666-5666-8666-ffffffffffff"


def _internal_headers() -> dict[str, str]:
    return {INTERNAL_TOKEN_HEADER: os.environ["INTERNAL_API_TOKEN"]}


def _seed_available_evidence(client: TestClient, csrf_headers: dict[str, str], evidence_dir) -> int:
    response = client.post(
        "/api/cameras",
        json={"name": "front-door", "stream_reference": STREAM},
        headers=csrf_headers,
    )
    assert response.status_code == 201, response.text
    camera_id = response.json()["id"]

    transition = eb.opened(camera_id=camera_id, event_id=EVENT_ID)
    response = client.post(
        "/api/internal/events",
        json={"action": transition.action.value, "event": transition.event.model_dump(mode="json")},
        headers=_internal_headers(),
    )
    assert response.status_code == 200, response.text

    relative = "camera-1/2026/10/29/evt-snapshot.jpg"
    target = evidence_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"jpeg-bytes")
    response = client.post(
        f"/api/internal/events/{EVENT_ID}/evidence",
        json={
            "event_id": EVENT_ID,
            "media_type": "snapshot",
            "status": "available",
            "relative_path": relative,
            "captured_at": datetime.now(UTC).isoformat(),
        },
        headers=_internal_headers(),
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_protection_requires_authentication(client: TestClient) -> None:
    assert (
        client.patch("/api/evidence/1", json={"retention_status": "protected"}).status_code == 401
    )


def test_protection_requires_csrf(
    auth_client: TestClient, csrf_headers: dict[str, str], evidence_dir
) -> None:
    evidence_id = _seed_available_evidence(auth_client, csrf_headers, evidence_dir)
    response = auth_client.patch(
        f"/api/evidence/{evidence_id}", json={"retention_status": "protected"}
    )
    assert response.status_code == 403


def test_protect_and_release_evidence(
    auth_client: TestClient, csrf_headers: dict[str, str], evidence_dir
) -> None:
    evidence_id = _seed_available_evidence(auth_client, csrf_headers, evidence_dir)

    protected = auth_client.patch(
        f"/api/evidence/{evidence_id}",
        json={"retention_status": "protected"},
        headers=csrf_headers,
    )
    assert protected.status_code == 200, protected.text
    assert protected.json()["retention_status"] == "protected"

    released = auth_client.patch(
        f"/api/evidence/{evidence_id}",
        json={"retention_status": "retained"},
        headers=csrf_headers,
    )
    assert released.status_code == 200, released.text
    assert released.json()["retention_status"] == "retained"


def test_protection_rejects_deleted_state(
    auth_client: TestClient, csrf_headers: dict[str, str], evidence_dir, db_session_factory
) -> None:
    evidence_id = _seed_available_evidence(auth_client, csrf_headers, evidence_dir)
    db: Session = db_session_factory()
    try:
        row = evidence_repo.get_by_id(db, evidence_id)
        row.retention_status = RetentionStatus.DELETED.value
        db.commit()
    finally:
        db.close()

    response = auth_client.patch(
        f"/api/evidence/{evidence_id}",
        json={"retention_status": "protected"},
        headers=csrf_headers,
    )
    assert response.status_code == 409


def test_protection_unknown_returns_404(
    auth_client: TestClient, csrf_headers: dict[str, str], evidence_dir
) -> None:
    response = auth_client.patch(
        "/api/evidence/9999", json={"retention_status": "protected"}, headers=csrf_headers
    )
    assert response.status_code == 404


def test_protection_rejects_deleted_target(
    auth_client: TestClient, csrf_headers: dict[str, str], evidence_dir
) -> None:
    evidence_id = _seed_available_evidence(auth_client, csrf_headers, evidence_dir)
    response = auth_client.patch(
        f"/api/evidence/{evidence_id}",
        json={"retention_status": "deleted"},
        headers=csrf_headers,
    )
    assert response.status_code == 422


def test_protected_evidence_survives_time_and_cap_eviction(
    auth_client: TestClient, csrf_headers: dict[str, str], evidence_dir, db_session_factory
) -> None:
    """Protected evidence is never deleted, even when everything else is expired/over cap."""
    evidence_id = _seed_available_evidence(auth_client, csrf_headers, evidence_dir)
    response = auth_client.patch(
        f"/api/evidence/{evidence_id}",
        json={"retention_status": "protected"},
        headers=csrf_headers,
    )
    assert response.status_code == 200, response.text

    db: Session = db_session_factory()
    try:
        # Expire everything by moving "now" far past the retention window, and set a zero
        # storage cap so the cap branch would also try to evict.
        report = evidence_service.run_retention(
            db,
            now=datetime.now(UTC) + timedelta(days=3650),
            retention_days=1,
            storage_limit_bytes=0,
        )
        row = evidence_repo.get_by_id(db, evidence_id)
    finally:
        db.close()

    assert report.deleted == 0
    assert report.blocked_by_protection is True
    assert row is not None
    assert row.retention_status == RetentionStatus.PROTECTED.value
    assert (evidence_dir / row.relative_path).is_file()
