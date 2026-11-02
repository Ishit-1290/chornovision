"""Tests for the camera configuration API (W §10)."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import AuditLog, Camera
from app.utils import utcnow

STREAM = "rtsp://192.168.1.10:554/stream1"


def _create(client: TestClient, headers: dict[str, str], **overrides: object):
    body = {"name": "front-door", "stream_reference": STREAM, **overrides}
    return client.post("/api/cameras", json=body, headers=headers)


# --- authentication / authorization --------------------------------------------


def test_camera_endpoints_require_authentication(client: TestClient) -> None:
    assert client.get("/api/cameras").status_code == 401
    assert client.get("/api/cameras/1").status_code == 401
    assert (
        client.post("/api/cameras", json={"name": "x", "stream_reference": STREAM}).status_code
        == 401
    )
    assert client.patch("/api/cameras/1", json={"name": "y"}).status_code == 401


def test_create_and_update_require_csrf(auth_client: TestClient) -> None:
    assert (
        auth_client.post(
            "/api/cameras", json={"name": "front-door", "stream_reference": STREAM}
        ).status_code
        == 403
    )
    response = _create(auth_client, {"X-CSRF-Token": "wrong"})
    assert response.status_code == 403


# --- create --------------------------------------------------------------------


def test_create_camera(auth_client: TestClient, csrf_headers: dict[str, str]) -> None:
    response = _create(auth_client, csrf_headers)
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "front-door"
    assert body["stream_reference"] == STREAM
    assert body["status"] == "configured"
    assert body["enabled"] is True
    assert body["id"] > 0


def test_create_stores_full_reference_but_redacts_response(
    auth_client: TestClient, csrf_headers: dict[str, str], db_session_factory
) -> None:
    reference = "rtsp://192.168.1.10:554/live?token=secret-token"
    response = _create(auth_client, csrf_headers, stream_reference=reference)
    assert response.status_code == 201
    assert response.json()["stream_reference"] == "rtsp://192.168.1.10:554/live"
    assert "secret-token" not in response.text

    db: Session = db_session_factory()
    try:
        camera = db.execute(select(Camera).where(Camera.name == "front-door")).scalar_one()
        assert camera.stream_reference == reference
    finally:
        db.close()


def test_create_rejects_duplicate_name(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    assert _create(auth_client, csrf_headers).status_code == 201
    assert _create(auth_client, csrf_headers).status_code == 409


def test_create_rejects_embedded_credentials(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    response = _create(
        auth_client, csrf_headers, stream_reference="rtsp://admin:secret@192.168.1.10/live"
    )
    assert response.status_code == 422
    assert "secret" not in response.text


def test_create_rejects_loopback_and_metadata(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    for reference in ("rtsp://127.0.0.1/live", "rtsp://169.254.169.254/live"):
        assert _create(auth_client, csrf_headers, stream_reference=reference).status_code == 422


def test_create_rejects_unsupported_scheme(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    response = _create(auth_client, csrf_headers, stream_reference="http://192.168.1.10/live")
    assert response.status_code == 422


def test_create_rejects_invalid_payload(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    assert auth_client.post("/api/cameras", json={}, headers=csrf_headers).status_code == 422
    assert _create(auth_client, csrf_headers, name="   ").status_code == 422


def test_create_records_audit_log(
    auth_client: TestClient, csrf_headers: dict[str, str], db_session_factory
) -> None:
    camera_id = _create(auth_client, csrf_headers).json()["id"]
    db: Session = db_session_factory()
    try:
        log = db.execute(select(AuditLog).where(AuditLog.action == "camera_created")).scalar_one()
        assert log.resource_type == "camera"
        assert log.resource_id == str(camera_id)
    finally:
        db.close()


# --- list / get -----------------------------------------------------------------


def test_list_and_get(auth_client: TestClient, csrf_headers: dict[str, str]) -> None:
    camera_id = _create(auth_client, csrf_headers).json()["id"]
    listed = auth_client.get("/api/cameras")
    assert listed.status_code == 200
    assert [c["id"] for c in listed.json()] == [camera_id]

    fetched = auth_client.get(f"/api/cameras/{camera_id}")
    assert fetched.status_code == 200
    assert fetched.json()["name"] == "front-door"

    assert auth_client.get("/api/cameras/999").status_code == 404


# --- update ---------------------------------------------------------------------


def test_update_name_enabled_and_configuration(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    camera_id = _create(auth_client, csrf_headers).json()["id"]
    response = auth_client.patch(
        f"/api/cameras/{camera_id}",
        json={
            "name": "back-door",
            "configuration": {
                "zones": [
                    {
                        "id": "entrance",
                        "name": "Front entrance",
                        "kind": "entrance",
                        "polygon": [
                            {"x": 0.0, "y": 0.0},
                            {"x": 1.0, "y": 0.0},
                            {"x": 1.0, "y": 1.0},
                        ],
                        "boundary": {
                            "p1": {"x": 0.0, "y": 0.5},
                            "p2": {"x": 1.0, "y": 0.5},
                            "inside_side": "left",
                        },
                    }
                ],
                "event_rules": {"entrance_zone_id": "entrance"},
            },
        },
        headers=csrf_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "back-door"
    assert body["configuration"]["event_rules"]["entrance_zone_id"] == "entrance"
    assert body["configuration"]["zones"][0]["id"] == "entrance"


def test_disable_camera_stops_processing_camera(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    camera_id = _create(auth_client, csrf_headers).json()["id"]
    # Start monitoring so the camera enters a processing state.
    assert auth_client.post("/api/monitoring/start", headers=csrf_headers).status_code == 200
    assert auth_client.get(f"/api/cameras/{camera_id}").json()["status"] == "connecting"

    response = auth_client.patch(
        f"/api/cameras/{camera_id}", json={"enabled": False}, headers=csrf_headers
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["status"] == "stopped"


def test_update_rejects_bad_stream_and_duplicate_name(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    first = _create(auth_client, csrf_headers, name="one").json()["id"]
    _create(auth_client, csrf_headers, name="two")

    assert (
        auth_client.patch(
            f"/api/cameras/{first}",
            json={"stream_reference": "rtsp://127.0.0.1/live"},
            headers=csrf_headers,
        ).status_code
        == 422
    )
    assert (
        auth_client.patch(
            f"/api/cameras/{first}", json={"name": "two"}, headers=csrf_headers
        ).status_code
        == 409
    )
    assert (
        auth_client.patch(
            "/api/cameras/999", json={"name": "ghost"}, headers=csrf_headers
        ).status_code
        == 404
    )


def test_update_records_field_names_only(
    auth_client: TestClient, csrf_headers: dict[str, str], db_session_factory
) -> None:
    camera_id = _create(auth_client, csrf_headers).json()["id"]
    auth_client.patch(
        f"/api/cameras/{camera_id}",
        json={"stream_reference": "rtsp://10.0.0.9:554/new"},
        headers=csrf_headers,
    )
    db: Session = db_session_factory()
    try:
        log = db.execute(select(AuditLog).where(AuditLog.action == "camera_updated")).scalar_one()
        assert log.log_metadata == {"fields": ["stream_reference"]}
        # The raw stream reference must never reach the audit log.
        assert "10.0.0.9" not in str(log.log_metadata)
    finally:
        db.close()


# --- effective lifecycle status (read-time projection) -------------------------


def _force_status(db_session_factory, camera_id: int, status: str, *, age: timedelta) -> None:
    """Persist ``status`` with an ``updated_at`` in the past, bypassing ORM onupdate."""
    db: Session = db_session_factory()
    try:
        db.execute(
            update(Camera)
            .where(Camera.id == camera_id)
            .values(status=status, updated_at=utcnow() - age)
        )
        db.commit()
    finally:
        db.close()


def test_camera_list_reports_stale_connecting_as_disconnected(
    auth_client: TestClient, csrf_headers: dict[str, str], db_session_factory
) -> None:
    """A silent worker must not leave ``GET /api/cameras`` stuck on ``connecting``.

    Regression: the response returned the raw persisted status, so a camera whose worker
    died mid-``connecting`` stayed ``connecting`` forever instead of the effective
    ``disconnected`` that ``GET /api/monitoring/status`` already reported.
    """
    camera_id = _create(auth_client, csrf_headers).json()["id"]
    _force_status(db_session_factory, camera_id, "connecting", age=timedelta(hours=1))

    response = auth_client.get("/api/cameras")
    assert response.status_code == 200
    camera = next(item for item in response.json() if item["id"] == camera_id)
    assert camera["status"] == "disconnected"

    # Single-camera read must agree with the list.
    assert auth_client.get(f"/api/cameras/{camera_id}").json()["status"] == "disconnected"


def test_camera_list_keeps_fresh_connecting_state(
    auth_client: TestClient, csrf_headers: dict[str, str], db_session_factory
) -> None:
    """A recently reporting camera keeps its real ``connecting`` state (no over-projection)."""
    camera_id = _create(auth_client, csrf_headers).json()["id"]
    _force_status(db_session_factory, camera_id, "connecting", age=timedelta(seconds=1))

    camera = next(
        item for item in auth_client.get("/api/cameras").json() if item["id"] == camera_id
    )
    assert camera["status"] == "connecting"
