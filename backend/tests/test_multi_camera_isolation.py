"""Multi-camera isolation, attribution, and NFR-01 tests (Phase 8; FR-06, AC-04).

These exercise the backend side of the multi-camera contract:

* per-camera worker-health keying, so one camera's staleness never projects another camera;
* monitoring is process-level and survives a browser logout (NFR-01);
* events and evidence stay attributed to the correct camera under interleaved and
  out-of-order delivery, and repeated delivery stays idempotent.

The database is the same in-memory SQLite fixture used by the rest of the suite.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.internal import INTERNAL_TOKEN_HEADER
from app.models.camera import Camera
from app.repositories import cameras as cameras_repo
from app.services import monitoring_service
from app.services.worker_registry import get_worker_registry
from app.utils import utcnow

from . import event_builders as eb

STREAM_A = "rtsp://192.168.1.10:554/s1"
STREAM_B = "rtsp://192.168.1.11:554/s2"
EVENT_A = "11111111-1111-5111-8111-111111111111"
EVENT_B = "22222222-2222-5222-8222-222222222222"


def _internal_headers() -> dict[str, str]:
    return {INTERNAL_TOKEN_HEADER: os.environ["INTERNAL_API_TOKEN"]}


def _create_camera(client: TestClient, headers: dict[str, str], name: str, stream: str) -> dict:
    response = client.post(
        "/api/cameras",
        json={"name": name, "stream_reference": stream},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _payload(transition) -> dict:
    return {"action": transition.action.value, "event": transition.event.model_dump(mode="json")}


def _submit_event(client: TestClient, transition) -> dict:
    response = client.post(
        "/api/internal/events", json=_payload(transition), headers=_internal_headers()
    )
    assert response.status_code == 200, response.text
    return response.json()


# --- per-camera staleness projection --------------------------------------------


def _camera_row(camera_id: int, name: str, stream: str) -> Camera:
    return Camera(
        id=camera_id,
        name=name,
        stream_reference=stream,
        enabled=True,
        status="active",
        configuration={},
        updated_at=utcnow() - timedelta(hours=1),
    )


def test_staleness_projection_is_per_camera(admin_env) -> None:
    stale = _camera_row(1, "cam-a", STREAM_A)
    fresh = _camera_row(2, "cam-b", STREAM_B)
    # Only camera 2 is heartbeating; camera 1's worker has silently died.
    get_worker_registry().record(2, "active")

    assert monitoring_service.effective_status(stale) == "disconnected"
    assert monitoring_service.effective_status(fresh) == "active"


def test_a_dead_camera_does_not_project_a_live_camera_as_disconnected(
    auth_client: TestClient, csrf_headers: dict[str, str], client: TestClient, db_session_factory
) -> None:
    camera_a = _create_camera(auth_client, csrf_headers, "cam-a", STREAM_A)
    camera_b = _create_camera(auth_client, csrf_headers, "cam-b", STREAM_B)
    auth_client.post("/api/monitoring/start", headers=csrf_headers)

    # Camera A reported active and then died: stale row, no live heartbeat.
    db: Session = db_session_factory()
    try:
        row = cameras_repo.get_by_id(db, camera_a["id"])
        assert row is not None
        row.status = "active"
        row.updated_at = utcnow() - timedelta(hours=1)
        db.commit()
    finally:
        db.close()

    # Camera B is live and continuously reporting.
    response = client.post(
        f"/api/internal/cameras/{camera_b['id']}/state",
        json={"status": "active"},
        headers=_internal_headers(),
    )
    assert response.json()["applied"] is True

    status = auth_client.get("/api/monitoring/status").json()
    by_id = {camera["id"]: camera["status"] for camera in status["cameras"]}
    assert by_id[camera_a["id"]] == "disconnected"
    assert by_id[camera_b["id"]] == "active"


# --- monitoring is independent of browser sessions (NFR-01) ---------------------


def test_monitoring_survives_browser_logout(
    auth_client: TestClient, csrf_headers: dict[str, str], client: TestClient
) -> None:
    camera = _create_camera(auth_client, csrf_headers, "cam-a", STREAM_A)
    auth_client.post("/api/monitoring/start", headers=csrf_headers)

    logout = auth_client.post("/api/auth/logout", headers=csrf_headers)
    assert logout.status_code == 200

    # The worker keeps reporting on the internal channel after the session ended.
    response = client.post(
        f"/api/internal/cameras/{camera['id']}/state",
        json={"status": "active"},
        headers=_internal_headers(),
    )
    assert response.json()["applied"] is True

    # A brand-new session sees monitoring still running, not reset by the logout.
    login = client.post(
        "/api/auth/login", json={"username": "admin", "password": "correct-horse-battery-staple"}
    )
    assert login.status_code == 200, login.text
    status = client.get("/api/monitoring/status").json()
    assert status["running"] is True
    assert status["cameras"][0]["status"] == "active"


def test_monitoring_survives_websocket_disconnect(
    auth_client: TestClient, csrf_headers: dict[str, str], client: TestClient
) -> None:
    camera = _create_camera(auth_client, csrf_headers, "cam-a", STREAM_A)
    auth_client.post("/api/monitoring/start", headers=csrf_headers)

    with auth_client.websocket_connect("/api/ws") as websocket:
        assert websocket.receive_json()["type"] == "ready"
    # The dashboard socket closed, but monitoring is independent of it.
    assert auth_client.get("/api/monitoring/status").json()["running"] is True
    response = client.post(
        f"/api/internal/cameras/{camera['id']}/state",
        json={"status": "active"},
        headers=_internal_headers(),
    )
    assert response.json()["applied"] is True


# --- event attribution and integrity --------------------------------------------


def test_interleaved_and_out_of_order_events_stay_attributed(
    auth_client: TestClient, csrf_headers: dict[str, str], client: TestClient
) -> None:
    camera_a = _create_camera(auth_client, csrf_headers, "cam-a", STREAM_A)
    camera_b = _create_camera(auth_client, csrf_headers, "cam-b", STREAM_B)

    # Two cameras' handoffs deliver interleaved.
    _submit_event(client, eb.opened(event_id=EVENT_A, camera_id=camera_a["id"], state_version=1))
    _submit_event(client, eb.opened(event_id=EVENT_B, camera_id=camera_b["id"], state_version=1))
    _submit_event(
        client,
        eb.updated(event_id=EVENT_A, camera_id=camera_a["id"], state_version=2, confidence=0.5),
    )
    # A stale retry for camera A arrives late and must be a no-op.
    stale = _submit_event(
        client,
        eb.updated(event_id=EVENT_A, camera_id=camera_a["id"], state_version=1, confidence=0.99),
    )
    assert stale["applied"] is False

    listing = auth_client.get("/api/events").json()
    by_event_id = {item["event_id"]: item for item in listing["items"]}
    assert by_event_id[EVENT_A]["camera_id"] == camera_a["id"]
    assert by_event_id[EVENT_B]["camera_id"] == camera_b["id"]
    assert by_event_id[EVENT_A]["state_version"] == 2
    assert by_event_id[EVENT_A]["confidence"] == 0.5

    # Filtering by camera returns only that camera's events.
    only_b = auth_client.get(f"/api/events?camera_id={camera_b['id']}").json()
    assert only_b["total"] == 1
    assert only_b["items"][0]["event_id"] == EVENT_B


def test_evidence_is_attributed_to_its_own_event(
    auth_client: TestClient,
    csrf_headers: dict[str, str],
    client: TestClient,
    evidence_dir,
) -> None:
    camera_a = _create_camera(auth_client, csrf_headers, "cam-a", STREAM_A)
    camera_b = _create_camera(auth_client, csrf_headers, "cam-b", STREAM_B)
    _submit_event(client, eb.opened(event_id=EVENT_A, camera_id=camera_a["id"]))
    _submit_event(client, eb.opened(event_id=EVENT_B, camera_id=camera_b["id"]))

    relative = "camera-2/2026/10/30/event-b-snapshot.jpg"
    target = evidence_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\xff\xd8\xff")

    response = client.post(
        f"/api/internal/events/{EVENT_B}/evidence",
        json={
            "event_id": EVENT_B,
            "media_type": "snapshot",
            "status": "available",
            "relative_path": relative,
            "captured_at": datetime.now(UTC).isoformat(),
        },
        headers=_internal_headers(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "available"

    listing = auth_client.get("/api/events").json()
    pk_by_event = {item["event_id"]: item["id"] for item in listing["items"]}
    detail_b = auth_client.get(f"/api/events/{pk_by_event[EVENT_B]}").json()
    detail_a = auth_client.get(f"/api/events/{pk_by_event[EVENT_A]}").json()
    assert [item["media_type"] for item in detail_b["evidence"]] == ["snapshot"]
    assert detail_a["evidence"] == []
