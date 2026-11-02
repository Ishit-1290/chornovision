"""Tests for the health endpoints."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from app.db import get_db
from app.main import app as fastapi_app


def test_health_reports_ok_with_working_database(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["app_name"] == "ChronoVision"
    assert body["environment"] == "test"


def test_health_never_includes_secrets(client: TestClient) -> None:
    body = client.get("/api/health").text
    assert "postgres" not in body.lower()
    assert "secret" not in body.lower()


def test_health_reports_degraded_when_database_unavailable(client: TestClient) -> None:
    class BrokenSession:
        def execute(self, *args: object, **kwargs: object) -> object:
            raise SQLAlchemyError("database down")

        def close(self) -> None:
            return None

    def broken_get_db() -> Iterator[BrokenSession]:
        yield BrokenSession()

    fastapi_app.dependency_overrides[get_db] = broken_get_db
    try:
        response = client.get("/api/health")
    finally:
        fastapi_app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "unavailable"


def test_camera_health_is_empty_with_no_cameras(client: TestClient) -> None:
    response = client.get("/api/health/cameras")
    assert response.status_code == 200
    assert response.json() == {"count": 0, "by_status": {}, "cameras": []}
