"""Tests for the internal worker→backend channel (OQ-09, D-12, Phase 4)."""

from __future__ import annotations

import os
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.internal import INTERNAL_TOKEN_HEADER

STREAM = "rtsp://192.168.1.10:554/stream1"


def _internal_headers() -> dict[str, str]:
    return {INTERNAL_TOKEN_HEADER: os.environ["INTERNAL_API_TOKEN"]}


def _create_camera(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.post(
        "/api/cameras",
        json={"name": "front-door", "stream_reference": STREAM},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


# --- authentication -------------------------------------------------------------


def test_internal_endpoints_require_token(client: TestClient) -> None:
    assert client.get("/api/internal/cameras").status_code == 401
    assert client.post("/api/internal/reconcile", json={}).status_code == 401
    assert (
        client.post(
            "/api/internal/cameras/1/state",
            json={"status": "active"},
            headers={INTERNAL_TOKEN_HEADER: "wrong-token"},
        ).status_code
        == 401
    )


def test_internal_endpoints_ignore_cookie_session(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    """A valid user session must not grant access to the internal channel."""
    assert auth_client.get("/api/internal/cameras").status_code == 401


def test_internal_endpoints_accept_valid_token(client: TestClient) -> None:
    response = client.get("/api/internal/cameras", headers=_internal_headers())
    assert response.status_code == 200
    assert response.json() == {"monitoring_state": "stopped", "cameras": []}


def test_internal_routes_are_hidden_from_openapi(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert not any(path.startswith("/api/internal") for path in schema["paths"])


# --- runtime plan ---------------------------------------------------------------


def test_runtime_plan_reports_requested_state_and_cameras(
    auth_client: TestClient, csrf_headers: dict[str, str], client: TestClient
) -> None:
    camera = _create_camera(auth_client, csrf_headers)
    auth_client.post("/api/monitoring/start", headers=csrf_headers)

    plan = client.get("/api/internal/cameras", headers=_internal_headers()).json()
    assert plan["monitoring_state"] == "running"
    assert plan["cameras"] == [
        {
            "id": camera["id"],
            "name": "front-door",
            "stream_reference": STREAM,
            "enabled": True,
            "status": "connecting",
            "configuration": {},
        }
    ]


# --- state reports --------------------------------------------------------------


def test_state_report_applies_legal_transition(
    auth_client: TestClient, csrf_headers: dict[str, str], client: TestClient
) -> None:
    camera = _create_camera(auth_client, csrf_headers)
    auth_client.post("/api/monitoring/start", headers=csrf_headers)

    response = client.post(
        f"/api/internal/cameras/{camera['id']}/state",
        json={"status": "active", "detail": None, "metrics": {"frames_processed": 10}},
        headers=_internal_headers(),
    )
    assert response.status_code == 200
    assert response.json() == {"camera_id": camera["id"], "status": "active", "applied": True}

    status = auth_client.get("/api/monitoring/status").json()
    assert status["cameras"][0]["status"] == "active"


def test_state_report_same_state_is_idempotent(
    auth_client: TestClient, csrf_headers: dict[str, str], client: TestClient
) -> None:
    camera = _create_camera(auth_client, csrf_headers)
    auth_client.post("/api/monitoring/start", headers=csrf_headers)
    url = f"/api/internal/cameras/{camera['id']}/state"
    first = client.post(url, json={"status": "active"}, headers=_internal_headers())
    second = client.post(url, json={"status": "active"}, headers=_internal_headers())
    assert first.json()["applied"] is True
    assert second.status_code == 200
    assert second.json()["applied"] is False


def test_state_report_illegal_transition_returns_409(
    auth_client: TestClient, csrf_headers: dict[str, str], client: TestClient
) -> None:
    camera = _create_camera(auth_client, csrf_headers)
    auth_client.post("/api/monitoring/start", headers=csrf_headers)
    # connecting -> degraded is not a legal lifecycle edge.
    response = client.post(
        f"/api/internal/cameras/{camera['id']}/state",
        json={"status": "degraded"},
        headers=_internal_headers(),
    )
    assert response.status_code == 409
    assert response.json()["current_status"] == "connecting"


def test_state_report_unknown_camera_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/internal/cameras/999/state",
        json={"status": "active"},
        headers=_internal_headers(),
    )
    assert response.status_code == 404


def test_state_report_rejects_unknown_status(client: TestClient) -> None:
    response = client.post(
        "/api/internal/cameras/1/state",
        json={"status": "teleporting"},
        headers=_internal_headers(),
    )
    assert response.status_code == 422


# --- reconcile ------------------------------------------------------------------


def test_reconcile_resets_processing_cameras(
    auth_client: TestClient, csrf_headers: dict[str, str], client: TestClient
) -> None:
    _create_camera(auth_client, csrf_headers)
    auth_client.post("/api/monitoring/start", headers=csrf_headers)

    response = client.post("/api/internal/reconcile", json={}, headers=_internal_headers())
    assert response.status_code == 200
    assert response.json() == {"reconciled": 1}
    assert auth_client.get("/api/monitoring/status").json()["cameras"][0]["status"] == "stopped"


# --- staleness projection -------------------------------------------------------


def test_stale_active_camera_is_projected_disconnected(
    auth_client: TestClient,
    csrf_headers: dict[str, str],
    client: TestClient,
    db_session_factory,
) -> None:
    from app.repositories import cameras as cameras_repo
    from app.utils import utcnow

    camera = _create_camera(auth_client, csrf_headers)
    auth_client.post("/api/monitoring/start", headers=csrf_headers)

    # Simulate a worker that reported ``active`` and then died: set the row active with an
    # old ``updated_at`` and no registry report.
    db: Session = db_session_factory()
    try:
        row = cameras_repo.get_by_id(db, camera["id"])
        assert row is not None
        row.status = "active"
        row.updated_at = utcnow() - timedelta(hours=1)
        db.commit()
    finally:
        db.close()

    status = auth_client.get("/api/monitoring/status").json()
    assert status["cameras"][0]["status"] == "disconnected"

    health = client.get("/api/health/cameras").json()
    assert health["by_status"] == {"disconnected": 1}
    assert health["cameras"] == [{"id": camera["id"], "status": "disconnected"}]
