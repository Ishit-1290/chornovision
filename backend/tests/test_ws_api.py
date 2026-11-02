"""Dashboard WebSocket authorization and notification delivery (Phase 7; FR-48, SEC-04)."""

from __future__ import annotations

import pytest
from starlette.websockets import WebSocketDisconnect

from app.services.event_broadcaster import get_event_broadcaster


def test_websocket_rejects_unauthenticated_client(client) -> None:
    with client.websocket_connect("/api/ws") as websocket:
        message = websocket.receive_json()
        assert message["type"] == "error"
        assert message["detail"] == "Not authenticated"
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()


def test_websocket_sends_ready_and_receives_notifications(auth_client) -> None:
    with auth_client.websocket_connect("/api/ws") as websocket:
        ready = websocket.receive_json()
        assert ready["type"] == "ready"
        assert ready["user"]["username"] == "admin"

        # Publishing from the test thread exercises the same thread-safe path a request
        # handler uses (FR-48: live updates without a manual refresh).
        get_event_broadcaster().publish({"type": "camera", "camera": {"id": 1, "status": "active"}})
        assert websocket.receive_json() == {
            "type": "camera",
            "camera": {"id": 1, "status": "active"},
        }


def test_revoked_session_is_rejected(auth_client, csrf_headers) -> None:
    logout = auth_client.post("/api/auth/logout", headers=csrf_headers)
    assert logout.status_code == 200

    with auth_client.websocket_connect("/api/ws") as websocket:
        assert websocket.receive_json()["type"] == "error"
        with pytest.raises(WebSocketDisconnect):
            websocket.receive_json()


def test_websocket_sessions_tear_down_cleanly(auth_client) -> None:
    """Repeated connect/close cycles must not leak a cancellation on teardown.

    Regression guard for the handler's cleanup: when the server cancels the ASGI
    task while it is closing, any ``await`` in the ``finally`` block can surface a
    spurious ``CancelledError``. Exercises that path several times so a regression
    is caught even though it is timing dependent.
    """
    for _ in range(5):
        with auth_client.websocket_connect("/api/ws") as websocket:
            assert websocket.receive_json()["type"] == "ready"
