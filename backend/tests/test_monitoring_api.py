"""Tests for the monitoring control plane (FR-47, W §10)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog

STREAM = "rtsp://192.168.1.10:554/stream1"


def _create(client: TestClient, headers: dict[str, str], **overrides: object) -> dict:
    body = {"name": "front-door", "stream_reference": STREAM, **overrides}
    response = client.post("/api/cameras", json=body, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


# --- authentication -------------------------------------------------------------


def test_monitoring_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/monitoring/status").status_code == 401
    assert client.post("/api/monitoring/start").status_code == 401
    assert client.post("/api/monitoring/pause").status_code == 401
    assert client.post("/api/monitoring/stop").status_code == 401


def test_monitoring_commands_require_csrf(auth_client: TestClient) -> None:
    assert auth_client.post("/api/monitoring/start").status_code == 403
    assert auth_client.get("/api/monitoring/status").status_code == 200


# --- state machine --------------------------------------------------------------


def test_status_starts_stopped(auth_client: TestClient) -> None:
    body = auth_client.get("/api/monitoring/status").json()
    assert body["state"] == "stopped"
    assert body["running"] is False
    assert body["cameras"] == []


def test_start_moves_enabled_cameras_to_connecting(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    _create(auth_client, csrf_headers)
    response = auth_client.post("/api/monitoring/start", headers=csrf_headers)
    assert response.status_code == 200
    assert response.json() == {"state": "running", "affected": 1}

    status = auth_client.get("/api/monitoring/status").json()
    assert status["state"] == "running"
    assert status["running"] is True
    assert status["cameras"][0]["status"] == "connecting"
    # Phase 3 has no worker, so the API must never claim the camera is active.
    assert status["cameras"][0]["status"] != "active"


def test_start_ignores_disabled_cameras(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    _create(auth_client, csrf_headers, enabled=False)
    response = auth_client.post("/api/monitoring/start", headers=csrf_headers)
    assert response.json()["affected"] == 0
    assert auth_client.get("/api/monitoring/status").json()["cameras"][0]["status"] == "configured"


def test_start_is_idempotent(auth_client: TestClient, csrf_headers: dict[str, str]) -> None:
    _create(auth_client, csrf_headers)
    first = auth_client.post("/api/monitoring/start", headers=csrf_headers).json()
    second = auth_client.post("/api/monitoring/start", headers=csrf_headers).json()
    assert first["affected"] == 1
    assert second == {"state": "running", "affected": 0}


def test_pause_stops_cameras(auth_client: TestClient, csrf_headers: dict[str, str]) -> None:
    _create(auth_client, csrf_headers)
    auth_client.post("/api/monitoring/start", headers=csrf_headers)
    response = auth_client.post("/api/monitoring/pause", headers=csrf_headers)
    assert response.status_code == 200
    assert response.json() == {"state": "paused", "affected": 1}
    status = auth_client.get("/api/monitoring/status").json()
    assert status["state"] == "paused"
    assert status["running"] is False
    assert status["cameras"][0]["status"] == "stopped"


def test_pause_while_stopped_conflicts(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    response = auth_client.post("/api/monitoring/pause", headers=csrf_headers)
    assert response.status_code == 409
    assert auth_client.get("/api/monitoring/status").json()["state"] == "stopped"


def test_stop_from_running_and_idempotent(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    _create(auth_client, csrf_headers)
    auth_client.post("/api/monitoring/start", headers=csrf_headers)
    stopped = auth_client.post("/api/monitoring/stop", headers=csrf_headers)
    assert stopped.json() == {"state": "stopped", "affected": 1}
    again = auth_client.post("/api/monitoring/stop", headers=csrf_headers)
    assert again.json() == {"state": "stopped", "affected": 0}
    assert auth_client.get("/api/monitoring/status").json()["cameras"][0]["status"] == "stopped"


def test_resume_after_pause_restarts_cameras(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    _create(auth_client, csrf_headers)
    auth_client.post("/api/monitoring/start", headers=csrf_headers)
    auth_client.post("/api/monitoring/pause", headers=csrf_headers)
    resumed = auth_client.post("/api/monitoring/start", headers=csrf_headers)
    assert resumed.json() == {"state": "running", "affected": 1}
    assert auth_client.get("/api/monitoring/status").json()["cameras"][0]["status"] == "connecting"


def test_monitoring_commands_are_audited(
    auth_client: TestClient, csrf_headers: dict[str, str], db_session_factory
) -> None:
    auth_client.post("/api/monitoring/start", headers=csrf_headers)
    auth_client.post("/api/monitoring/stop", headers=csrf_headers)
    db: Session = db_session_factory()
    try:
        actions = {
            log.action
            for log in db.execute(
                select(AuditLog).where(AuditLog.resource_type == "monitoring")
            ).scalars()
        }
        assert actions == {"monitoring_started", "monitoring_stopped"}
    finally:
        db.close()


def test_camera_health_reports_lifecycle_states(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    _create(auth_client, csrf_headers)
    auth_client.post("/api/monitoring/start", headers=csrf_headers)
    body = auth_client.get("/api/health/cameras").json()
    assert body["count"] == 1
    assert body["by_status"] == {"connecting": 1}
    assert body["cameras"] == [{"id": body["cameras"][0]["id"], "status": "connecting"}]
    # Health must not expose the stream reference or camera name.
    assert "stream_reference" not in str(body)
    assert "front-door" not in str(body)
