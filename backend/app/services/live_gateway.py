"""MediaMTX management-API client used for live playback (Phase 10; D-62/D-65).

The gateway is a **trusted internal service** configured by the operator (``MEDIAMTX_API_URL``).
This client therefore only ever requests fixed ``/v3/...`` endpoints on that base URL; it is
not a general-purpose URL fetcher and cannot be pointed at a camera or arbitrary destination.

Camera source URLs passed to :meth:`LiveGateway.ensure_path` may contain credentials. They are
placed in the request body only. They are never logged, returned, or included in an exception
message; errors carry a short machine-readable reason instead.

A gateway outage is a first-class, non-fatal condition: every method raises
:class:`GatewayError` and the caller degrades live playback to "unavailable" without touching
camera monitoring, events, or evidence.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import quote

from app.config import Settings


class GatewayError(Exception):
    """A gateway operation failed. ``reason`` is a short non-sensitive code."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class GatewayPathStatus:
    """Runtime state of one gateway path (never includes the source address)."""

    registered: bool
    online: bool
    ready: bool
    readers: int
    tracks: int


class LiveGateway:
    """Thin, dependency-free client for the MediaMTX v3 HTTP API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base = settings.mediamtx_api_url.rstrip("/")

    # -- identity ---------------------------------------------------------------
    def path_name(self, camera_id: int) -> str:
        """Stable, safe gateway path for a camera (``<prefix>-cam-<id>``)."""
        return f"{self._settings.mediamtx_path_prefix}-cam-{camera_id}"

    def whep_url(self, camera_id: int) -> str:
        """Browser-facing WHEP endpoint for a camera (no camera source or credentials)."""
        base = self._settings.mediamtx_webrtc_url.rstrip("/")
        return f"{base}/{quote(self.path_name(camera_id), safe='')}/whep"

    # -- operations -------------------------------------------------------------
    def health(self) -> tuple[bool, str]:
        """Return ``(reachable, detail)`` without raising."""
        try:
            self._request("GET", "/v3/config/global/get")
        except GatewayError as exc:
            return False, exc.reason
        return True, "ok"

    def ensure_path(self, camera_id: int, source_url: str) -> None:
        """Create or update the gateway path for ``camera_id``.

        The source is pulled on demand (only while a viewer is connected), so registration
        is cheap and an idle camera is not connected twice.
        """
        name = self.path_name(camera_id)
        close_after = max(0, self._settings.live_gateway_close_after_seconds)
        body: dict[str, object] = {
            "source": source_url,
            "sourceOnDemand": True,
            "sourceOnDemandStartTimeout": "10s",
            "sourceOnDemandCloseAfter": f"{close_after}s",
            "rtspTransport": "tcp",
        }
        try:
            self._request("GET", f"/v3/config/paths/get/{name}")
        except GatewayError as exc:
            if exc.reason != "not_found":
                raise
            self._request("POST", f"/v3/config/paths/add/{name}", body)
            return
        self._request("PATCH", f"/v3/config/paths/patch/{name}", body)

    def remove_path(self, camera_id: int) -> None:
        """Delete a camera's gateway path (idempotent)."""
        name = self.path_name(camera_id)
        try:
            self._request("DELETE", f"/v3/config/paths/delete/{name}")
        except GatewayError as exc:
            if exc.reason == "not_found":
                return
            raise

    def path_status(self, camera_id: int) -> GatewayPathStatus:
        """Return runtime status for a path; an unknown path is ``registered=False``."""
        name = self.path_name(camera_id)
        try:
            payload = self._request("GET", f"/v3/paths/get/{name}")
        except GatewayError as exc:
            if exc.reason == "not_found":
                return GatewayPathStatus(False, False, False, 0, 0)
            raise
        # MediaMTX v1.21.x reports ``readers`` as an array of reader objects; some
        # versions/endpoints report a plain count. Accept both so a gateway shape change
        # can never turn a read-only status call into an HTTP 500.
        readers_raw = payload.get("readers", 0)
        if isinstance(readers_raw, list):
            readers = len(readers_raw)
        else:
            try:
                readers = int(readers_raw or 0)
            except (TypeError, ValueError):
                readers = 0
        return GatewayPathStatus(
            registered=True,
            online=bool(payload.get("online", False)),
            ready=bool(payload.get("ready", False)),
            readers=readers,
            tracks=len(payload.get("tracks") or []),
        )

    # -- transport --------------------------------------------------------------
    def _request(self, method: str, path: str, body: dict[str, object] | None = None) -> dict:
        url = f"{self._base}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        username = self._settings.mediamtx_api_username
        password = self._settings.mediamtx_api_password.get_secret_value()
        if username or password:
            token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
            headers["Authorization"] = f"Basic {token}"

        request = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(
                request, timeout=self._settings.mediamtx_request_timeout_seconds
            ) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise GatewayError("not_found", "gateway path not found") from exc
            if exc.code in (401, 403):
                raise GatewayError(
                    "unauthorized", "gateway rejected the management API credentials"
                ) from exc
            if exc.code == 400:
                raise GatewayError("rejected", "gateway rejected the path configuration") from exc
            raise GatewayError("http_error", f"gateway returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise GatewayError("unreachable", "gateway is unreachable") from exc

        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise GatewayError("invalid_response", "gateway returned an invalid response") from exc
        return payload if isinstance(payload, dict) else {}
