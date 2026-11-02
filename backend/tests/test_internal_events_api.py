"""Internal event/evidence submission endpoints (Phase 6; D-12)."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.auth.internal import INTERNAL_TOKEN_HEADER

from . import event_builders as eb

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


def _payload(transition) -> dict:
    return {
        "action": transition.action.value,
        "event": transition.event.model_dump(mode="json"),
    }


# --- events ---------------------------------------------------------------------


def test_submit_event_requires_token(client: TestClient) -> None:
    response = client.post("/api/internal/events", json=_payload(eb.opened()))
    assert response.status_code == 401


def test_submit_event_persists_and_is_idempotent(
    auth_client: TestClient, csrf_headers: dict[str, str], client: TestClient
) -> None:
    camera = _create_camera(auth_client, csrf_headers)
    body = _payload(eb.opened(camera_id=camera["id"]))

    first = client.post("/api/internal/events", json=body, headers=_internal_headers())
    assert first.status_code == 200, first.text
    assert first.json()["applied"] is True

    second = client.post("/api/internal/events", json=body, headers=_internal_headers())
    assert second.status_code == 200
    assert second.json()["applied"] is False

    listing = auth_client.get("/api/events").json()
    assert listing["total"] == 1
    assert listing["items"][0]["camera_id"] == camera["id"]


def test_submit_event_stale_is_noop(
    auth_client: TestClient, csrf_headers: dict[str, str], client: TestClient
) -> None:
    camera = _create_camera(auth_client, csrf_headers)
    client.post(
        "/api/internal/events",
        json=_payload(eb.opened(camera_id=camera["id"], state_version=1)),
        headers=_internal_headers(),
    )
    client.post(
        "/api/internal/events",
        json=_payload(eb.updated(camera_id=camera["id"], state_version=3)),
        headers=_internal_headers(),
    )
    stale = client.post(
        "/api/internal/events",
        json=_payload(eb.updated(camera_id=camera["id"], state_version=2)),
        headers=_internal_headers(),
    )
    assert stale.json()["applied"] is False
    assert stale.json()["state_version"] == 3


def test_submit_event_unknown_camera_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/internal/events",
        json=_payload(eb.opened(camera_id=999)),
        headers=_internal_headers(),
    )
    assert response.status_code == 404


def test_submit_event_rejects_unknown_field(client: TestClient) -> None:
    body = _payload(eb.opened())
    body["unexpected"] = "value"
    response = client.post("/api/internal/events", json=body, headers=_internal_headers())
    assert response.status_code == 422


def test_submit_event_rejects_action_status_mismatch(client: TestClient) -> None:
    body = _payload(eb.opened())
    body["action"] = "resolved"  # opened+active is not a resolved transition
    response = client.post("/api/internal/events", json=body, headers=_internal_headers())
    assert response.status_code == 422


# --- evidence -------------------------------------------------------------------


def _register(client: TestClient, event_id: str, payload: dict):
    return client.post(
        f"/api/internal/events/{event_id}/evidence", json=payload, headers=_internal_headers()
    )


def test_register_evidence_available_requires_and_verifies_file(
    auth_client: TestClient, csrf_headers: dict[str, str], client: TestClient, evidence_dir
) -> None:
    camera = _create_camera(auth_client, csrf_headers)
    event_payload = _payload(eb.opened(camera_id=camera["id"]))
    client.post("/api/internal/events", json=event_payload, headers=_internal_headers())
    event_id = event_payload["event"]["event_id"]

    relative = "camera-1/2026/10/29/evt-snapshot.jpg"
    target = evidence_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"\xff\xd8\xff")

    response = _register(
        client,
        event_id,
        {
            "event_id": event_id,
            "media_type": "snapshot",
            "status": "available",
            "relative_path": relative,
            "captured_at": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "available"

    detail = auth_client.get("/api/events/1").json()
    assert detail["evidence"][0]["media_type"] == "snapshot"
    assert detail["evidence_refs"] == [f"snapshot:{detail['evidence'][0]['id']}"]


def test_register_evidence_marks_missing_file_failed(
    auth_client: TestClient, csrf_headers: dict[str, str], client: TestClient, evidence_dir
) -> None:
    camera = _create_camera(auth_client, csrf_headers)
    event_payload = _payload(eb.opened(camera_id=camera["id"]))
    client.post("/api/internal/events", json=event_payload, headers=_internal_headers())
    event_id = event_payload["event"]["event_id"]

    response = _register(
        client,
        event_id,
        {
            "event_id": event_id,
            "media_type": "clip",
            "status": "available",
            "relative_path": "camera-1/missing.mp4",
            "captured_at": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "failed"


def test_register_evidence_rejects_traversal_path(
    auth_client: TestClient, csrf_headers: dict[str, str], client: TestClient, evidence_dir
) -> None:
    camera = _create_camera(auth_client, csrf_headers)
    event_payload = _payload(eb.opened(camera_id=camera["id"]))
    client.post("/api/internal/events", json=event_payload, headers=_internal_headers())
    event_id = event_payload["event"]["event_id"]

    response = _register(
        client,
        event_id,
        {
            "event_id": event_id,
            "media_type": "snapshot",
            "status": "available",
            "relative_path": "../../etc/passwd",
            "captured_at": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "failed"


def test_register_evidence_failed_requires_error(client: TestClient) -> None:
    response = _register(
        client,
        "some-event",
        {
            "event_id": "some-event",
            "media_type": "snapshot",
            "status": "failed",
            "captured_at": datetime.now(UTC).isoformat(),
        },
    )
    # Pydantic validation rejects a failed registration without an error reason.
    assert response.status_code == 422


def test_register_evidence_unknown_event_returns_404(client: TestClient) -> None:
    response = _register(
        client,
        "does-not-exist",
        {
            "event_id": "does-not-exist",
            "media_type": "snapshot",
            "status": "failed",
            "error": "encode_failed",
            "captured_at": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 404


def test_register_evidence_path_body_mismatch_returns_422(client: TestClient) -> None:
    response = _register(
        client,
        "event-a",
        {
            "event_id": "event-b",
            "media_type": "snapshot",
            "status": "pending",
            "captured_at": datetime.now(UTC).isoformat(),
        },
    )
    assert response.status_code == 422
