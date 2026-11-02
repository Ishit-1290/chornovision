"""Authorized evidence delivery and path confinement (Phase 6; SEC-08)."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.internal import INTERNAL_TOKEN_HEADER

from . import event_builders as eb

STREAM = "rtsp://192.168.1.10:554/stream1"
EVENT_ID = "33333333-3333-5333-8333-cccccccccccc"


def _internal_headers() -> dict[str, str]:
    return {INTERNAL_TOKEN_HEADER: os.environ["INTERNAL_API_TOKEN"]}


def _create_camera(client: TestClient, csrf_headers: dict[str, str]) -> int:
    response = client.post(
        "/api/cameras",
        json={"name": "front-door", "stream_reference": STREAM},
        headers=csrf_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_event(client: TestClient, camera_id: int) -> None:
    transition = eb.opened(camera_id=camera_id, event_id=EVENT_ID)
    payload = {
        "action": transition.action.value,
        "event": transition.event.model_dump(mode="json"),
    }
    response = client.post("/api/internal/events", json=payload, headers=_internal_headers())
    assert response.status_code == 200, response.text


def _register(
    client: TestClient, media_type: str, status: str, relative_path: str | None = None, **extra
) -> int:
    body = {
        "event_id": EVENT_ID,
        "media_type": media_type,
        "status": status,
        "captured_at": datetime.now(UTC).isoformat(),
    }
    if relative_path is not None:
        body["relative_path"] = relative_path
    body.update(extra)
    response = client.post(
        f"/api/internal/events/{EVENT_ID}/evidence", json=body, headers=_internal_headers()
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_evidence_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/evidence/1").status_code == 401


def test_authorized_evidence_is_served(
    auth_client: TestClient, csrf_headers: dict[str, str], evidence_dir
) -> None:
    camera_id = _create_camera(auth_client, csrf_headers)
    _create_event(auth_client, camera_id)
    relative = "camera-1/2026/10/29/evt-snapshot.jpg"
    target = evidence_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"jpeg-bytes")
    evidence_id = _register(auth_client, "snapshot", "available", relative)

    response = auth_client.get(f"/api/evidence/{evidence_id}")
    assert response.status_code == 200
    assert response.content == b"jpeg-bytes"
    assert response.headers["content-type"].startswith("image/jpeg")


def test_unknown_evidence_returns_404(auth_client: TestClient) -> None:
    assert auth_client.get("/api/evidence/9999").status_code == 404


def test_deleted_evidence_returns_410(
    auth_client: TestClient, csrf_headers: dict[str, str], evidence_dir, db_session_factory
) -> None:
    from app.models.evidence import RetentionStatus
    from app.repositories import evidence as evidence_repo

    camera_id = _create_camera(auth_client, csrf_headers)
    _create_event(auth_client, camera_id)
    evidence_id = _register(auth_client, "snapshot", "failed", error="encode_failed")

    db: Session = db_session_factory()
    try:
        row = evidence_repo.get_by_id(db, evidence_id)
        row.retention_status = RetentionStatus.DELETED.value
        db.commit()
    finally:
        db.close()
    assert auth_client.get(f"/api/evidence/{evidence_id}").status_code == 410


def test_pending_evidence_returns_409(
    auth_client: TestClient, csrf_headers: dict[str, str], evidence_dir
) -> None:
    camera_id = _create_camera(auth_client, csrf_headers)
    _create_event(auth_client, camera_id)
    evidence_id = _register(auth_client, "snapshot", "pending")
    assert auth_client.get(f"/api/evidence/{evidence_id}").status_code == 409


def test_unsafe_stored_path_is_not_served(
    auth_client: TestClient, csrf_headers: dict[str, str], evidence_dir, db_session_factory
) -> None:
    from app.models.evidence import EvidenceStatus
    from app.repositories import evidence as evidence_repo

    camera_id = _create_camera(auth_client, csrf_headers)
    _create_event(auth_client, camera_id)
    relative = "camera-1/2026/10/29/evt-snapshot.jpg"
    target = evidence_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"jpeg-bytes")
    evidence_id = _register(auth_client, "snapshot", "available", relative)

    # Corrupt the stored path after the fact: the row claims available but escapes the root.
    db: Session = db_session_factory()
    try:
        row = evidence_repo.get_by_id(db, evidence_id)
        row.relative_path = "../../etc/passwd"
        row.status = EvidenceStatus.AVAILABLE.value
        db.commit()
    finally:
        db.close()
    assert auth_client.get(f"/api/evidence/{evidence_id}").status_code == 404


def test_missing_file_returns_409(
    auth_client: TestClient, csrf_headers: dict[str, str], evidence_dir
) -> None:
    camera_id = _create_camera(auth_client, csrf_headers)
    _create_event(auth_client, camera_id)
    relative = "camera-1/2026/10/29/evt-snapshot.jpg"
    target = evidence_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"jpeg-bytes")
    evidence_id = _register(auth_client, "snapshot", "available", relative)

    target.unlink()
    assert auth_client.get(f"/api/evidence/{evidence_id}").status_code == 409
