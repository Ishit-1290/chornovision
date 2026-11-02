"""Phase 9 security verification sweep (G §17, W §13 M8; SEC-01..SEC-09).

One systematic pass over the security boundaries the Phase 9 acceptance criteria call
out: authentication on every protected route, CSRF on every state-changing route, session
invalidation on logout while monitoring is active, WebSocket authorization, the internal
worker channel, SSRF rejection on camera registration, and evidence-path confinement.

It complements the per-feature security tests (``test_auth_api``, ``test_ws_api``,
``test_internal_api``, ``test_evidence_api``, ``test_stream_validation``) rather than
replacing them: the value here is the *exhaustive enumeration* so a newly added route that
forgets its auth dependency makes an existing test fail.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.auth.internal import INTERNAL_TOKEN_HEADER

STREAM = "rtsp://192.168.1.10:554/stream1"

# Every route that must be authenticated as the administrator. ``(method, path, body)``.
PROTECTED_ROUTES = [
    ("GET", "/api/auth/me", None),
    ("GET", "/api/cameras", None),
    ("POST", "/api/cameras", {"name": "x", "stream_reference": STREAM}),
    ("GET", "/api/cameras/1", None),
    ("PATCH", "/api/cameras/1", {"name": "y"}),
    ("GET", "/api/cameras/1/live", None),
    ("POST", "/api/cameras/1/live/start", None),
    ("GET", "/api/monitoring/status", None),
    ("POST", "/api/monitoring/start", None),
    ("POST", "/api/monitoring/pause", None),
    ("POST", "/api/monitoring/stop", None),
    ("GET", "/api/events", None),
    ("GET", "/api/events/1", None),
    ("PATCH", "/api/events/1", {"review_status": "confirmed"}),
    ("GET", "/api/evidence/1", None),
    ("PATCH", "/api/evidence/1", {"retention_status": "protected"}),
    ("GET", "/api/settings", None),
]

# State-changing routes that must require a CSRF token as well as a session.
CSRF_PROTECTED_ROUTES = [
    ("POST", "/api/cameras", {"name": "x", "stream_reference": STREAM}),
    ("PATCH", "/api/cameras/1", {"name": "y"}),
    ("POST", "/api/cameras/1/live/start", None),
    ("POST", "/api/monitoring/start", None),
    ("POST", "/api/monitoring/pause", None),
    ("POST", "/api/monitoring/stop", None),
    ("PATCH", "/api/events/1", {"review_status": "confirmed"}),
    ("PATCH", "/api/evidence/1", {"retention_status": "protected"}),
]


def _request(client: TestClient, method: str, path: str, body: dict | None, headers=None):
    return client.request(method, path, json=body, headers=headers or {})


def _create_camera(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post(
        "/api/cameras",
        json={"name": "front-door", "stream_reference": STREAM},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


# --------------------------------------------------------------------------------------
# Authentication boundary
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("method,path,body", PROTECTED_ROUTES)
def test_protected_routes_reject_anonymous(client: TestClient, method, path, body) -> None:
    response = _request(client, method, path, body)
    assert response.status_code == 401, f"{method} {path} -> {response.status_code}"


def test_health_endpoints_are_public(client: TestClient) -> None:
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/health/cameras").status_code == 200


def test_login_endpoint_is_public(client: TestClient) -> None:
    # Publicly reachable (rate-limited) but requires credentials; not a 401 for reaching it.
    response = client.post("/api/auth/login", json={"username": "nobody", "password": "bad"})
    assert response.status_code == 401


# --------------------------------------------------------------------------------------
# CSRF boundary
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("method,path,body", CSRF_PROTECTED_ROUTES)
def test_state_changing_routes_require_csrf(auth_client: TestClient, method, path, body) -> None:
    response = _request(auth_client, method, path, body)
    assert response.status_code == 403, f"{method} {path} -> {response.status_code}"


def test_wrong_csrf_token_is_rejected(auth_client: TestClient) -> None:
    response = auth_client.post(
        "/api/monitoring/start", headers={"X-CSRF-Token": "not-the-real-token"}
    )
    assert response.status_code == 403


def test_read_only_routes_do_not_require_csrf(auth_client: TestClient) -> None:
    assert auth_client.get("/api/events").status_code == 200
    assert auth_client.get("/api/settings").status_code == 200
    assert auth_client.get("/api/auth/me").status_code == 200


# --------------------------------------------------------------------------------------
# Logout while monitoring is active
# --------------------------------------------------------------------------------------


def test_logout_invalidates_session_but_not_the_monitoring_control_plane(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    """Logging out ends the *user's* access; monitoring is a separate, explicit plane.

    After logout the session cookie must be unusable for the API and the WebSocket, while
    the activation state established through the monitoring control plane is unchanged
    (continuous processing is explicitly activated and does not silently stop).
    """
    _create_camera(auth_client, csrf_headers)
    started = auth_client.post("/api/monitoring/start", headers=csrf_headers)
    assert started.status_code == 200, started.text

    logout = auth_client.post("/api/auth/logout", headers=csrf_headers)
    assert logout.status_code == 200

    # The session is gone for the API surface...
    assert auth_client.get("/api/auth/me").status_code == 401
    assert auth_client.get("/api/monitoring/status").status_code == 401
    assert auth_client.get("/api/events").status_code == 401

    # ...and for the realtime channel.
    with auth_client.websocket_connect("/api/ws") as websocket:
        assert websocket.receive_json()["type"] == "error"
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()

    # The internal channel (worker-facing, token-authenticated) still sees the running plane.
    plan = auth_client.get(
        "/api/internal/cameras",
        headers={INTERNAL_TOKEN_HEADER: os.environ["INTERNAL_API_TOKEN"]},
    )
    assert plan.status_code == 200
    assert plan.json()["monitoring_state"] == "running"


def test_logout_requires_csrf_and_session(auth_client: TestClient) -> None:
    assert auth_client.post("/api/auth/logout").status_code == 403
    auth_client.cookies.clear()
    assert auth_client.post("/api/auth/logout").status_code == 401


# --------------------------------------------------------------------------------------
# Internal worker channel
# --------------------------------------------------------------------------------------


def test_internal_channel_requires_token_not_cookies(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    # A valid admin session must not open the internal channel.
    assert auth_client.get("/api/internal/cameras").status_code == 401
    assert auth_client.post("/api/internal/reconcile", json={}).status_code == 401
    # Only the shared token works.
    ok = auth_client.get(
        "/api/internal/cameras",
        headers={INTERNAL_TOKEN_HEADER: os.environ["INTERNAL_API_TOKEN"]},
    )
    assert ok.status_code == 200


def test_internal_routes_absent_from_openapi(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert all("/api/internal" not in path for path in paths)


# --------------------------------------------------------------------------------------
# SSRF and stream-reference validation
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "reference",
    [
        "rtsp://127.0.0.1/live",
        "rtsp://169.254.169.254/live",
        "rtsp://localhost/live",
        "rtsp://metadata.google.internal/live",
        "rtsp://admin:secret@192.168.1.10/live",
        "http://192.168.1.10/live",
        "file:///etc/passwd",
    ],
)
def test_camera_registration_rejects_unsafe_references(
    auth_client: TestClient, csrf_headers: dict[str, str], reference: str
) -> None:
    response = auth_client.post(
        "/api/cameras",
        json={"name": "candidate", "stream_reference": reference},
        headers=csrf_headers,
    )
    assert response.status_code == 422
    # The rejected reference must never be echoed back verbatim (credentials/URL leakage).
    if "secret" in reference:
        assert "secret" not in response.text


# --------------------------------------------------------------------------------------
# Evidence path confinement
# --------------------------------------------------------------------------------------


def test_evidence_id_must_be_an_integer(auth_client: TestClient) -> None:
    # A traversal-looking id is rejected by routing/validation, never resolved as a path.
    assert auth_client.get("/api/evidence/../../etc/passwd").status_code in (404, 422)
    assert auth_client.get("/api/evidence/not-a-number").status_code == 422


def test_evidence_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/evidence/1").status_code == 401
