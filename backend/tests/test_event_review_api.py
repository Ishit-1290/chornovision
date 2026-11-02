"""Human-review mutation and timeline ordering/filtering (Phase 7; FR-44, OQ-10)."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.internal import INTERNAL_TOKEN_HEADER
from app.models.audit_log import AuditLog

from . import event_builders as eb

STREAM = "rtsp://192.168.1.10:554/stream1"
EVENT_A = "44444444-4444-5444-8444-dddddddddddd"
EVENT_B = "55555555-5555-5555-8555-eeeeeeeeeeee"


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


def _submit(client: TestClient, transition) -> None:
    response = client.post(
        "/api/internal/events",
        json={"action": transition.action.value, "event": transition.event.model_dump(mode="json")},
        headers=_internal_headers(),
    )
    assert response.status_code == 200, response.text


def _seed(client: TestClient, csrf_headers: dict[str, str]) -> int:
    camera_id = _create_camera(client, csrf_headers)
    _submit(client, eb.opened(camera_id=camera_id, event_id=EVENT_A))
    _submit(
        client,
        eb.opened(camera_id=camera_id, event_id=EVENT_B, offset_seconds=30.0),
    )
    return camera_id


def test_review_requires_authentication(client: TestClient) -> None:
    assert client.patch("/api/events/1", json={"review_status": "confirmed"}).status_code == 401


def test_review_requires_csrf(auth_client: TestClient, csrf_headers: dict[str, str]) -> None:
    _seed(auth_client, csrf_headers)
    response = auth_client.patch("/api/events/1", json={"review_status": "confirmed"})
    assert response.status_code == 403


def test_review_updates_status_and_writes_audit(
    auth_client: TestClient, csrf_headers: dict[str, str], db_session_factory
) -> None:
    _seed(auth_client, csrf_headers)

    response = auth_client.patch(
        "/api/events/1",
        json={"review_status": "confirmed", "note": "Person clearly entered"},
        headers=csrf_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["review_status"] == "confirmed"
    # The original deterministic message and lifecycle state are untouched (FR-44).
    assert body["message"]
    assert body["status"] == "active"

    detail = auth_client.get("/api/events/1").json()
    assert detail["review_status"] == "confirmed"

    db = db_session_factory()
    try:
        rows = list(
            db.execute(select(AuditLog).where(AuditLog.action == "event_reviewed")).scalars()
        )
    finally:
        db.close()
    assert len(rows) == 1
    assert rows[0].resource_type == "event"
    assert rows[0].log_metadata == {
        "from": "unreviewed",
        "to": "confirmed",
        "note": "Person clearly entered",
    }


def test_review_rejects_invalid_status(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    _seed(auth_client, csrf_headers)
    response = auth_client.patch(
        "/api/events/1", json={"review_status": "maybe"}, headers=csrf_headers
    )
    assert response.status_code == 422


def test_review_unknown_event_returns_404(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    response = auth_client.patch(
        "/api/events/9999", json={"review_status": "dismissed"}, headers=csrf_headers
    )
    assert response.status_code == 404


def test_events_filter_by_review_status(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    _seed(auth_client, csrf_headers)
    auth_client.patch("/api/events/1", json={"review_status": "dismissed"}, headers=csrf_headers)

    unreviewed = auth_client.get("/api/events", params={"review_status": "unreviewed"}).json()
    assert unreviewed["total"] == 1
    assert unreviewed["items"][0]["event_id"] == EVENT_B

    dismissed = auth_client.get("/api/events", params={"review_status": "dismissed"}).json()
    assert dismissed["total"] == 1
    assert dismissed["items"][0]["event_id"] == EVENT_A


def test_events_order_is_configurable(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    _seed(auth_client, csrf_headers)
    newest_first = auth_client.get("/api/events").json()["items"]
    oldest_first = auth_client.get("/api/events", params={"order": "asc"}).json()["items"]
    assert newest_first[0]["event_id"] == EVENT_B
    assert oldest_first[0]["event_id"] == EVENT_A
    assert auth_client.get("/api/events", params={"order": "sideways"}).status_code == 422
