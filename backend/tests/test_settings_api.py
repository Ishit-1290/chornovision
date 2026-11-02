"""Read-only system settings endpoint (Phase 7)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_settings_require_authentication(client: TestClient) -> None:
    assert client.get("/api/settings").status_code == 401


def test_settings_return_non_sensitive_policy(auth_client: TestClient, evidence_dir) -> None:
    response = auth_client.get("/api/settings")
    assert response.status_code == 200, response.text
    body = response.json()

    # Defaults from D-11/D-43; deletion remains explicit (never a capture side effect).
    assert body["evidence_retention_days"] == 30
    assert body["evidence_storage_limit_gb"] == 25
    assert body["evidence_retention_on_register"] is False
    assert body["evidence_rolling_buffer_seconds"] == 15
    assert body["evidence_pre_event_seconds"] == 5
    assert body["evidence_post_event_seconds"] == 5
    assert body["evidence_storage_used_bytes"] == 0

    # Never leak filesystem paths or secrets through the settings surface.
    assert "evidence_dir" not in body
    assert "secret" not in " ".join(body).lower()
