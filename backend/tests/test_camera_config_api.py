"""Tests for camera event-zone/rule configuration validation through the API (Phase 5)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Camera

STREAM = "rtsp://192.168.1.10:554/stream1"


def _valid_configuration() -> dict[str, object]:
    return {
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
        "event_rules": {
            "entrance_zone_id": "entrance",
            "thresholds": {"door_open_threshold_seconds": 90},
        },
    }


def _create(client: TestClient, headers: dict[str, str], **overrides: object):
    body: dict[str, object] = {
        "name": "front-door",
        "stream_reference": STREAM,
        **overrides,
    }
    return client.post("/api/cameras", json=body, headers=headers)


def _stored_configuration(db_session_factory, camera_id: int) -> dict[str, object]:
    db: Session = db_session_factory()
    try:
        camera = db.execute(select(Camera).where(Camera.id == camera_id)).scalar_one()
        return dict(camera.configuration or {})
    finally:
        db.close()


# --- create --------------------------------------------------------------------


def test_create_persists_a_valid_zone_configuration(
    auth_client: TestClient, csrf_headers: dict[str, str], db_session_factory
) -> None:
    configuration = _valid_configuration()
    response = _create(auth_client, csrf_headers, configuration=configuration)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["configuration"]["event_rules"]["entrance_zone_id"] == "entrance"
    assert _stored_configuration(db_session_factory, body["id"]) == configuration


def test_create_without_configuration_defaults_to_empty(
    auth_client: TestClient, csrf_headers: dict[str, str], db_session_factory
) -> None:
    response = _create(auth_client, csrf_headers)
    assert response.status_code == 201
    assert response.json()["configuration"] == {}
    assert _stored_configuration(db_session_factory, response.json()["id"]) == {}


def test_create_rejects_an_invalid_zone_reference(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    response = _create(
        auth_client,
        csrf_headers,
        configuration={"event_rules": {"room_zone_id": "missing"}},
    )
    assert response.status_code == 422
    assert "Invalid camera configuration" in response.text


def test_create_rejects_a_malformed_zone_polygon(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    response = _create(
        auth_client,
        csrf_headers,
        configuration={
            "zones": [
                {
                    "id": "entrance",
                    "name": "Entrance",
                    "kind": "entrance",
                    "polygon": [{"x": 0.0, "y": 0.0}],
                }
            ]
        },
    )
    assert response.status_code == 422


def test_create_rejects_out_of_range_coordinates(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    response = _create(
        auth_client,
        csrf_headers,
        configuration={
            "zones": [
                {
                    "id": "room",
                    "name": "Room",
                    "kind": "room",
                    "polygon": [
                        {"x": -0.5, "y": 0.0},
                        {"x": 1.0, "y": 0.0},
                        {"x": 1.0, "y": 1.0},
                    ],
                }
            ]
        },
    )
    assert response.status_code == 422


def test_create_rejects_invalid_rule_thresholds(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    response = _create(
        auth_client,
        csrf_headers,
        configuration={"event_rules": {"thresholds": {"door_open_threshold_seconds": 0}}},
    )
    assert response.status_code == 422


# --- update --------------------------------------------------------------------


def test_update_applies_a_valid_configuration(
    auth_client: TestClient, csrf_headers: dict[str, str], db_session_factory
) -> None:
    camera_id = _create(auth_client, csrf_headers).json()["id"]
    configuration = _valid_configuration()
    response = auth_client.patch(
        f"/api/cameras/{camera_id}",
        json={"configuration": configuration},
        headers=csrf_headers,
    )
    assert response.status_code == 200
    assert _stored_configuration(db_session_factory, camera_id) == configuration


def test_update_rejects_invalid_configuration_and_preserves_previous(
    auth_client: TestClient, csrf_headers: dict[str, str], db_session_factory
) -> None:
    configuration = _valid_configuration()
    camera_id = _create(auth_client, csrf_headers, configuration=configuration).json()["id"]

    response = auth_client.patch(
        f"/api/cameras/{camera_id}",
        json={"configuration": {"zones": "not-a-list"}},
        headers=csrf_headers,
    )
    assert response.status_code == 422
    assert "Invalid camera configuration" in response.text
    assert _stored_configuration(db_session_factory, camera_id) == configuration


def test_update_does_not_leak_rule_details_into_the_audit_log(
    auth_client: TestClient, csrf_headers: dict[str, str], db_session_factory
) -> None:
    from app.models import AuditLog

    camera_id = _create(auth_client, csrf_headers).json()["id"]
    auth_client.patch(
        f"/api/cameras/{camera_id}",
        json={"configuration": _valid_configuration()},
        headers=csrf_headers,
    )
    db: Session = db_session_factory()
    try:
        log = db.execute(select(AuditLog).where(AuditLog.action == "camera_updated")).scalar_one()
        assert log.log_metadata == {"fields": ["configuration"]}
    finally:
        db.close()


def test_configuration_requires_authentication(client: TestClient) -> None:
    assert (
        client.post(
            "/api/cameras",
            json={
                "name": "front-door",
                "stream_reference": STREAM,
                "configuration": _valid_configuration(),
            },
        ).status_code
        == 401
    )
