"""Live-playback integration tests (Phase 10; FR-51, D-62..D-65).

Covers the four boundaries the feature adds:

* credential storage is encrypted, write-only, and never echoed;
* live endpoints are authenticated (and the start endpoint is CSRF-protected);
* gateway states map to ``unavailable/connecting/live/disconnected`` and a gateway
  failure degrades *only* live playback;
* camera sources are validated/pinned before they reach the gateway (SSRF), and
  gateway paths stay unique and stable per camera.

The gateway itself is faked so the suite never needs MediaMTX or a real camera; the
actual v1.21.3 HTTP contract is verified separately in ``docs/LIVE_PLAYBACK.md``.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterator
from urllib.parse import unquote, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import clear_settings_cache, get_settings
from app.models import Camera
from app.services import live_service
from app.services.credential_cipher import (
    CredentialError,
    decrypt_credentials,
    encrypt_credentials,
)
from app.services.live_gateway import GatewayError, GatewayPathStatus, LiveGateway
from app.services.stream_validation import StreamValidationError

STREAM = "rtsp://192.168.1.10:554/stream1"

LIVE_ENV = {
    "LIVE_PLAYBACK_ENABLED": "true",
    "MEDIAMTX_API_URL": "http://127.0.0.1:9997",
    "MEDIAMTX_WEBRTC_URL": "http://127.0.0.1:8889",
}


@pytest.fixture
def live_env(admin_env: None) -> Iterator[None]:
    """Enable live playback for the duration of a test."""
    saved = {key: os.environ.get(key) for key in LIVE_ENV}
    os.environ.update(LIVE_ENV)
    clear_settings_cache()
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        clear_settings_cache()


class FakeGateway:
    """In-memory stand-in for :class:`LiveGateway`."""

    def __init__(self) -> None:
        self.paths: dict[int, str] = {}
        self.status = GatewayPathStatus(
            registered=False, online=False, ready=False, readers=0, tracks=0
        )
        self.fail_reason: str | None = None

    def path_name(self, camera_id: int) -> str:
        return f"cv-cam-{camera_id}"

    def whep_url(self, camera_id: int) -> str:
        return f"http://gateway.example:8889/cv-cam-{camera_id}/whep"

    def _maybe_fail(self) -> None:
        if self.fail_reason is not None:
            raise GatewayError(self.fail_reason, "fake gateway failure")

    def ensure_path(self, camera_id: int, source_url: str) -> None:
        self._maybe_fail()
        self.paths[camera_id] = source_url

    def remove_path(self, camera_id: int) -> None:
        self._maybe_fail()
        self.paths.pop(camera_id, None)

    def path_status(self, camera_id: int) -> GatewayPathStatus:
        self._maybe_fail()
        if camera_id not in self.paths:
            return GatewayPathStatus(False, False, False, 0, 0)
        return self.status


@pytest.fixture
def fake_gateway(monkeypatch: pytest.MonkeyPatch) -> FakeGateway:
    gateway = FakeGateway()
    monkeypatch.setattr(live_service, "_gateway", lambda: gateway)
    return gateway


def _create(client: TestClient, headers: dict[str, str], **overrides: object):
    body = {"name": "front-door", "stream_reference": STREAM, **overrides}
    return client.post("/api/cameras", json=body, headers=headers)


# --------------------------------------------------------------------------------------
# Credential storage (D-64)
# --------------------------------------------------------------------------------------


def test_credential_cipher_round_trip(admin_env) -> None:
    token = encrypt_credentials("operator", "p@ss:w/rd")
    assert token.startswith("v1:")
    assert "operator" not in token
    assert "p@ss" not in token
    assert decrypt_credentials(token) == ("operator", "p@ss:w/rd")


def test_credential_cipher_rejects_tampering(admin_env) -> None:
    token = encrypt_credentials("operator", "secret")
    with pytest.raises(CredentialError):
        decrypt_credentials(token[:-2] + "AA")
    with pytest.raises(CredentialError):
        decrypt_credentials("v9:not-a-real-token")
    with pytest.raises(CredentialError):
        decrypt_credentials("garbage")


def test_create_with_credentials_is_write_only(
    auth_client: TestClient, csrf_headers: dict[str, str], db_session_factory
) -> None:
    response = _create(
        auth_client,
        csrf_headers,
        stream_username="operator",
        stream_password="p@ss:w/rd",
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["has_stream_credentials"] is True
    assert "stream_username" not in body
    assert "stream_password" not in body
    assert "p@ss:w/rd" not in response.text

    db: Session = db_session_factory()
    try:
        camera = db.execute(select(Camera)).scalar_one()
        stored = camera.stream_credentials_encrypted
        assert stored is not None
        assert "p@ss:w/rd" not in stored
        assert decrypt_credentials(stored) == ("operator", "p@ss:w/rd")
    finally:
        db.close()


def test_credentials_must_be_provided_together(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    assert _create(auth_client, csrf_headers, stream_username="operator").status_code == 422
    assert _create(auth_client, csrf_headers, stream_password="secret").status_code == 422


def test_credentials_default_to_absent(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    response = _create(auth_client, csrf_headers)
    assert response.status_code == 201
    assert response.json()["has_stream_credentials"] is False


def test_update_sets_and_clears_credentials(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    camera_id = _create(auth_client, csrf_headers).json()["id"]

    updated = auth_client.patch(
        f"/api/cameras/{camera_id}",
        json={"stream_username": "operator", "stream_password": "secret"},
        headers=csrf_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["has_stream_credentials"] is True
    assert "secret" not in updated.text

    cleared = auth_client.patch(
        f"/api/cameras/{camera_id}",
        json={"clear_stream_credentials": True},
        headers=csrf_headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["has_stream_credentials"] is False


def test_clear_and_set_credentials_conflict(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    camera_id = _create(auth_client, csrf_headers).json()["id"]
    response = auth_client.patch(
        f"/api/cameras/{camera_id}",
        json={
            "clear_stream_credentials": True,
            "stream_username": "operator",
            "stream_password": "secret",
        },
        headers=csrf_headers,
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------------------
# Authentication / CSRF on the live endpoints
# --------------------------------------------------------------------------------------


def test_live_endpoints_require_authentication(client: TestClient) -> None:
    assert client.get("/api/cameras/1/live").status_code == 401
    assert client.post("/api/cameras/1/live/start").status_code == 401


def test_live_start_requires_csrf(auth_client: TestClient, csrf_headers: dict[str, str]) -> None:
    camera_id = _create(auth_client, csrf_headers).json()["id"]
    assert auth_client.post(f"/api/cameras/{camera_id}/live/start").status_code == 403


def test_live_endpoint_unknown_camera(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    assert auth_client.get("/api/cameras/999/live").status_code == 404
    assert auth_client.post("/api/cameras/999/live/start", headers=csrf_headers).status_code == 404


# --------------------------------------------------------------------------------------
# Availability & states
# --------------------------------------------------------------------------------------


def test_live_is_unavailable_when_not_configured(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    """Deploying MediaMTX alone must not enable playback (opt-in)."""
    camera_id = _create(auth_client, csrf_headers).json()["id"]
    response = auth_client.get(f"/api/cameras/{camera_id}/live")
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["state"] == "unavailable"
    assert body["whep_url"] is None
    assert body["path"] is None


def test_live_start_is_unavailable_when_not_configured(
    auth_client: TestClient, csrf_headers: dict[str, str]
) -> None:
    camera_id = _create(auth_client, csrf_headers).json()["id"]
    response = auth_client.post(f"/api/cameras/{camera_id}/live/start", headers=csrf_headers)
    assert response.status_code == 200
    assert response.json()["state"] == "unavailable"


def test_live_unavailable_when_camera_disabled(
    auth_client: TestClient, csrf_headers: dict[str, str], live_env, fake_gateway: FakeGateway
) -> None:
    camera_id = _create(auth_client, csrf_headers).json()["id"]
    auth_client.patch(f"/api/cameras/{camera_id}", json={"enabled": False}, headers=csrf_headers)
    body = auth_client.get(f"/api/cameras/{camera_id}/live").json()
    assert body["available"] is False
    assert body["state"] == "unavailable"


def test_live_start_reports_connecting(
    auth_client: TestClient, csrf_headers: dict[str, str], live_env, fake_gateway: FakeGateway
) -> None:
    camera_id = _create(auth_client, csrf_headers).json()["id"]

    response = auth_client.post(f"/api/cameras/{camera_id}/live/start", headers=csrf_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["available"] is True
    assert body["state"] == "connecting"
    assert body["protocol"] == "webrtc"
    assert body["path"] == f"cv-cam-{camera_id}"
    assert body["whep_url"].endswith(f"/cv-cam-{camera_id}/whep")
    assert camera_id in fake_gateway.paths


def test_live_state_when_gateway_reports_online(
    auth_client: TestClient, csrf_headers: dict[str, str], live_env, fake_gateway: FakeGateway
) -> None:
    camera_id = _create(auth_client, csrf_headers).json()["id"]
    fake_gateway.status = GatewayPathStatus(True, True, True, 1, 2)
    body = auth_client.get(f"/api/cameras/{camera_id}/live").json()
    assert body["state"] == "live"


def test_disconnected_state_when_source_not_producing(
    auth_client: TestClient, csrf_headers: dict[str, str], live_env, fake_gateway: FakeGateway
) -> None:
    camera_id = _create(auth_client, csrf_headers).json()["id"]
    fake_gateway.status = GatewayPathStatus(True, False, False, 1, 0)
    body = auth_client.get(f"/api/cameras/{camera_id}/live").json()
    assert body["state"] == "disconnected"


# --------------------------------------------------------------------------------------
# Gateway failure isolation
# --------------------------------------------------------------------------------------


def test_gateway_failure_does_not_break_camera_management(
    auth_client: TestClient, csrf_headers: dict[str, str], live_env, fake_gateway: FakeGateway
) -> None:
    fake_gateway.fail_reason = "unreachable"

    created = _create(auth_client, csrf_headers)
    assert created.status_code == 201, created.text
    camera_id = created.json()["id"]

    # Listing/reading cameras and monitoring are unaffected by the gateway outage.
    assert auth_client.get("/api/cameras").status_code == 200
    assert auth_client.get(f"/api/cameras/{camera_id}").status_code == 200
    assert auth_client.get("/api/monitoring/status").status_code == 200

    body = auth_client.get(f"/api/cameras/{camera_id}/live").json()
    assert body["available"] is False
    assert body["state"] == "unavailable"
    assert "unreachable" in body["detail"]


def test_start_playback_reports_unavailable_on_gateway_failure(
    auth_client: TestClient, csrf_headers: dict[str, str], live_env, fake_gateway: FakeGateway
) -> None:
    camera_id = _create(auth_client, csrf_headers).json()["id"]
    fake_gateway.fail_reason = "unreachable"
    response = auth_client.post(f"/api/cameras/{camera_id}/live/start", headers=csrf_headers)
    assert response.status_code == 200
    assert response.json()["state"] == "unavailable"


# --------------------------------------------------------------------------------------
# Path stability, uniqueness, and cleanup
# --------------------------------------------------------------------------------------


def test_paths_are_unique_and_stable_per_camera(
    auth_client: TestClient, csrf_headers: dict[str, str], live_env, fake_gateway: FakeGateway
) -> None:
    first = _create(auth_client, csrf_headers, name="front").json()["id"]
    second = _create(auth_client, csrf_headers, name="back").json()["id"]

    first_path = auth_client.get(f"/api/cameras/{first}/live").json()["path"]
    second_path = auth_client.get(f"/api/cameras/{second}/live").json()["path"]
    assert first_path != second_path
    assert first_path == f"cv-cam-{first}"
    assert second_path == f"cv-cam-{second}"

    # A repeated start refreshes the same path rather than creating a duplicate.
    auth_client.post(f"/api/cameras/{first}/live/start", headers=csrf_headers)
    assert set(fake_gateway.paths) == {first, second}


def test_disabling_camera_removes_gateway_path(
    auth_client: TestClient, csrf_headers: dict[str, str], live_env, fake_gateway: FakeGateway
) -> None:
    camera_id = _create(auth_client, csrf_headers).json()["id"]
    assert camera_id in fake_gateway.paths

    auth_client.patch(f"/api/cameras/{camera_id}", json={"enabled": False}, headers=csrf_headers)
    assert camera_id not in fake_gateway.paths


def test_gateway_source_is_never_exposed_in_responses(
    auth_client: TestClient, csrf_headers: dict[str, str], live_env, fake_gateway: FakeGateway
) -> None:
    camera_id = _create(
        auth_client, csrf_headers, stream_username="operator", stream_password="topsecret"
    ).json()["id"]
    response = auth_client.get(f"/api/cameras/{camera_id}/live")
    body = response.json()
    assert "topsecret" not in response.text
    assert "operator" not in response.text
    assert body["whep_url"] == f"http://gateway.example:8889/cv-cam-{camera_id}/whep"
    # The gateway did receive the credential-bearing source, but only server-side.
    assert "topsecret" in fake_gateway.paths[camera_id]


# --------------------------------------------------------------------------------------
# Source validation & pinning (SSRF)
# --------------------------------------------------------------------------------------


def test_gateway_source_url_rejects_prohibited_destinations(live_env) -> None:
    for reference in (
        "rtsp://127.0.0.1:554/live",
        "rtsp://169.254.169.254/live",
        "rtsp://[::1]/live",
    ):
        camera = Camera(name="x", stream_reference=reference)
        with pytest.raises(StreamValidationError):
            live_service.gateway_source_url(camera)


def test_gateway_source_url_injects_credentials(live_env) -> None:
    camera = Camera(name="x", stream_reference="rtsp://192.168.1.10:554/live")
    camera.stream_credentials_encrypted = encrypt_credentials("operator", "p@ss:w/rd")

    url = live_service.gateway_source_url(camera)
    parts = urlsplit(url)
    assert parts.hostname == "192.168.1.10"
    userinfo = parts.netloc.rsplit("@", 1)[0]
    username, _, password = userinfo.partition(":")
    assert unquote(username) == "operator"
    assert unquote(password) == "p@ss:w/rd"


def test_gateway_source_url_pins_plain_rtsp_hostname(live_env, monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_pin(reference: str, **kwargs: object) -> str:
        captured["reference"] = reference
        return "rtsp://10.0.0.9:554/live"

    monkeypatch.setattr(live_service, "pin_stream_host", fake_pin)
    camera = Camera(name="x", stream_reference="rtsp://camera.lan:554/live")
    assert live_service.gateway_source_url(camera) == "rtsp://10.0.0.9:554/live"
    assert captured["reference"] == "rtsp://camera.lan:554/live"


def test_gateway_source_url_does_not_pin_rtsps_hostname(live_env, monkeypatch) -> None:
    """TLS/SNI needs the real hostname; validation-only is the documented residual."""
    called: dict[str, object] = {}

    def fake_validate(reference: str, **kwargs: object) -> None:
        called["reference"] = reference

    monkeypatch.setattr(live_service, "validate_stream_host", fake_validate)
    camera = Camera(name="x", stream_reference="rtsps://camera.lan/stream")
    assert live_service.gateway_source_url(camera) == "rtsps://camera.lan/stream"
    assert called["reference"] == "rtsps://camera.lan/stream"


# --------------------------------------------------------------------------------------
# MediaMTX client contract (path naming + error mapping)
# --------------------------------------------------------------------------------------


def test_gateway_path_and_whep_urls(live_env) -> None:
    gateway = LiveGateway(get_settings())
    assert gateway.path_name(7) == "cv-cam-7"
    assert gateway.whep_url(7) == "http://127.0.0.1:8889/cv-cam-7/whep"


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload


def _http_error(url: str, code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, code, "error", {}, None)


def test_gateway_maps_http_status_codes(live_env, monkeypatch) -> None:
    gateway = LiveGateway(get_settings())

    def raise_404(request, timeout=None):
        raise _http_error(request.full_url, 404)

    monkeypatch.setattr(urllib.request, "urlopen", raise_404)
    assert gateway.path_status(1).registered is False

    def raise_401(request, timeout=None):
        raise _http_error(request.full_url, 401)

    monkeypatch.setattr(urllib.request, "urlopen", raise_401)
    with pytest.raises(GatewayError) as excinfo:
        gateway.ensure_path(1, "rtsp://192.168.1.10:554/live")
    assert excinfo.value.reason == "unauthorized"


def test_gateway_path_status_accepts_readers_array(live_env, monkeypatch) -> None:
    """MediaMTX v1.21.x reports ``readers`` as an array; that must not 500 the API.

    Regression for the HTTP 500 on ``GET /api/cameras/{id}/live``: the client used to call
    ``int()`` on the array, raising ``TypeError`` that surfaced as a 500.
    """
    gateway = LiveGateway(get_settings())
    payload = json.dumps(
        {
            "online": True,
            "ready": False,
            "readers": [{"id": "a"}, {"id": "b"}],
            "tracks": ["H264"],
        }
    ).encode()
    monkeypatch.setattr(
        urllib.request, "urlopen", lambda request, timeout=None: _FakeResponse(payload)
    )

    status = gateway.path_status(4)
    assert status.registered is True
    assert status.online is True
    assert status.readers == 2
    assert status.tracks == 1

    # Older mediaMTX versions report a plain count; keep accepting it too.
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse(b'{"readers": 3, "tracks": []}'),
    )
    assert gateway.path_status(4).readers == 3


def test_gateway_reports_unreachable(live_env, monkeypatch) -> None:
    gateway = LiveGateway(get_settings())

    def raise_url_error(request, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", raise_url_error)
    reachable, detail = gateway.health()
    assert reachable is False
    assert detail == "unreachable"


def test_gateway_ensure_path_creates_then_exposes_source_only_server_side(
    live_env, monkeypatch
) -> None:
    gateway = LiveGateway(get_settings())
    seen: list[tuple[str, str, bytes | None]] = []

    def fake_urlopen(request, timeout=None):
        seen.append((request.method, request.full_url, request.data))
        if request.method == "GET":
            raise _http_error(request.full_url, 404)
        return _FakeResponse(b"{}")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    gateway.ensure_path(3, "rtsp://operator:topsecret@10.0.0.3/live")

    assert [call[0] for call in seen] == ["GET", "POST"]
    assert seen[1][1].endswith("/v3/config/paths/add/cv-cam-3")
    body = json.loads(seen[1][2] or b"{}")
    assert body["source"] == "rtsp://operator:topsecret@10.0.0.3/live"
    assert body["sourceOnDemand"] is True
    assert body["rtspTransport"] == "tcp"
