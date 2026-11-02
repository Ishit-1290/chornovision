"""Event read endpoints (Phase 6; W §10)."""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from app.auth.internal import INTERNAL_TOKEN_HEADER
from app.events.types import EventType

from . import event_builders as eb

STREAM = "rtsp://192.168.1.10:554/stream1"
EVENT_A = "11111111-1111-5111-8111-aaaaaaaaaaaa"
EVENT_B = "22222222-2222-5222-8222-bbbbbbbbbbbb"


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


def _submit(client: TestClient, transition) -> None:
    response = client.post(
        "/api/internal/events",
        json={"action": transition.action.value, "event": transition.event.model_dump(mode="json")},
        headers=_internal_headers(),
    )
    assert response.status_code == 200, response.text


def test_events_require_authentication(client: TestClient) -> None:
    assert client.get("/api/events").status_code == 401
    assert client.get("/api/events/1").status_code == 401


def test_list_events_filters_and_paginates(
    auth_client: TestClient, csrf_headers: dict[str, str], client: TestClient
) -> None:
    camera = _create_camera(auth_client, csrf_headers)
    _submit(
        client,
        eb.opened(
            camera_id=camera["id"],
            event_id=EVENT_A,
            event_type=EventType.PERSON_ENTERING,
        ),
    )
    _submit(
        client,
        eb.opened(
            camera_id=camera["id"],
            event_id=EVENT_B,
            event_type=EventType.PERSON_LEAVING,
            offset_seconds=5.0,
        ),
    )

    listing = auth_client.get("/api/events").json()
    assert listing["total"] == 2
    assert {item["event_type"] for item in listing["items"]} == {
        "person_entering",
        "person_leaving",
    }

    filtered = auth_client.get("/api/events", params={"event_type": "person_entering"}).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["event_id"] == EVENT_A

    paged = auth_client.get("/api/events", params={"limit": 1, "offset": 1}).json()
    assert paged["limit"] == 1
    assert len(paged["items"]) == 1

    bad = auth_client.get("/api/events", params={"event_type": "not_a_type"})
    assert bad.status_code == 422


def test_event_detail_includes_transitions(
    auth_client: TestClient, csrf_headers: dict[str, str], client: TestClient
) -> None:
    camera = _create_camera(auth_client, csrf_headers)
    _submit(client, eb.opened(camera_id=camera["id"], event_id=EVENT_A, state_version=1))
    _submit(client, eb.resolved(camera_id=camera["id"], event_id=EVENT_A, state_version=2))

    detail = auth_client.get("/api/events/1").json()
    assert detail["status"] == "completed"
    assert [row["action"] for row in detail["transitions"]] == ["opened", "resolved"]
    assert detail["message"]


def test_event_detail_unknown_returns_404(auth_client: TestClient) -> None:
    assert auth_client.get("/api/events/9999").status_code == 404
