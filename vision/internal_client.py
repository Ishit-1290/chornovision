"""Worker → backend internal HTTP client (OQ-09, D-12).

The worker never writes to the database: it reports lifecycle state (and, from Phase 5,
events) to FastAPI internal endpoints over authenticated HTTP. The shared token is sent in
``X-Internal-Token`` and compared in constant time by the backend. This module uses only the
standard library for transport (no extra runtime dependency), but the transport is
injectable so tests are fully deterministic and never open a socket.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

INTERNAL_TOKEN_HEADER = "X-Internal-Token"


class InternalClientError(Exception):
    """The backend could not be reached or returned an unusable response.

    Treated as *transient* by the handoff: the item is retried with backoff.
    """


class PermanentInternalError(InternalClientError):
    """The backend definitively rejected the submission; retrying cannot succeed."""


@dataclass(frozen=True)
class PlanCamera:
    """A camera the worker may be asked to process."""

    id: int
    name: str
    stream_reference: str
    enabled: bool
    status: str
    configuration: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RuntimePlan:
    """The backend's *requested* runtime state."""

    monitoring_state: str
    cameras: list[PlanCamera]

    @property
    def running(self) -> bool:
        return self.monitoring_state == "running"

    def enabled_cameras(self) -> list[PlanCamera]:
        return [camera for camera in self.cameras if camera.enabled]


@dataclass(frozen=True)
class StateReport:
    """Result of a state report."""

    camera_id: int
    status: str
    applied: bool


@dataclass(frozen=True)
class EventSubmissionResult:
    """What the backend stored for one event transition (Phase 6; D-12)."""

    event_id: str
    state_version: int
    status: str
    #: ``False`` when the transition was an idempotent duplicate/stale no-op.
    applied: bool


@dataclass(frozen=True)
class EvidenceRegistrationResult:
    """What the backend stored for one evidence registration (Phase 6; FR-39)."""

    event_id: str
    media_type: str
    status: str
    retention_status: str
    applied: bool


#: ``transport(method, url, headers, body, timeout) -> (status_code, response_bytes)``.
Transport = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, bytes]]


def _urllib_transport(
    method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:  # non-2xx still carries a body
        return int(exc.code), exc.read()
    except urllib.error.URLError as exc:
        raise InternalClientError(str(exc.reason)) from exc


@dataclass
class InternalClient:
    """Minimal, retrying client for the backend internal API."""

    base_url: str
    token: str
    timeout: float = 5.0
    max_retries: int = 3
    retry_backoff_seconds: float = 0.2
    transport: Transport = _urllib_transport
    sleeper: Callable[[float], None] = time.sleep
    _base: str = field(init=False, default="")

    def __post_init__(self) -> None:
        self._base = self.base_url.rstrip("/")

    # -- public API ----------------------------------------------------------------
    def fetch_plan(self) -> RuntimePlan:
        status, payload = self._request("GET", "/api/internal/cameras")
        if status != 200:
            raise InternalClientError(f"plan request failed with status {status}")
        data = _decode(payload)
        cameras = [
            PlanCamera(
                id=int(item["id"]),
                name=str(item["name"]),
                stream_reference=str(item["stream_reference"]),
                enabled=bool(item["enabled"]),
                status=str(item["status"]),
                configuration=dict(item.get("configuration") or {}),
            )
            for item in data.get("cameras", [])
        ]
        return RuntimePlan(
            monitoring_state=str(data.get("monitoring_state", "stopped")), cameras=cameras
        )

    def report_state(
        self,
        camera_id: int,
        status: str,
        *,
        detail: str | None = None,
        metrics: dict[str, Any] | None = None,
    ) -> StateReport:
        body = json.dumps({"status": status, "detail": detail, "metrics": metrics}).encode("utf-8")
        http_status, payload = self._request(
            "POST", f"/api/internal/cameras/{camera_id}/state", body=body
        )
        data = _decode(payload) if payload else {}
        if http_status in (200, 409):
            return StateReport(
                camera_id=camera_id,
                status=str(data.get("status") or data.get("current_status") or status),
                applied=http_status == 200 and bool(data.get("applied", False)),
            )
        raise InternalClientError(
            f"state report for camera {camera_id} failed with status {http_status}"
        )

    def reconcile(self) -> int:
        """Ask the backend to reset cameras left in a processing state (worker startup)."""
        status, payload = self._request("POST", "/api/internal/reconcile", body=b"{}")
        if status != 200:
            raise InternalClientError(f"reconcile failed with status {status}")
        return int(_decode(payload).get("reconciled", 0))

    # -- events / evidence (Phase 6) -----------------------------------------------
    def submit_event(self, payload: dict[str, Any]) -> EventSubmissionResult:
        """Submit one event transition (idempotent by ``event_id``/``state_version``)."""
        body = json.dumps(payload).encode("utf-8")
        status, raw = self._request("POST", "/api/internal/events", body=body)
        if status in (404, 422):
            # Unknown camera or a payload the backend will never accept.
            raise PermanentInternalError(f"event submission rejected with status {status}")
        if status != 200:
            raise InternalClientError(f"event submission failed with status {status}")
        data = _decode(raw)
        return EventSubmissionResult(
            event_id=str(data.get("event_id") or payload.get("event", {}).get("event_id", "")),
            state_version=int(data.get("state_version", 0)),
            status=str(data.get("status", "")),
            applied=bool(data.get("applied", False)),
        )

    def register_evidence(
        self, event_id: str, payload: dict[str, Any]
    ) -> EvidenceRegistrationResult:
        """Register one snapshot/clip for an event.

        A 404 is *retryable*: evidence may be delivered before the backend has committed the
        event (delivery is at-least-once and re-ordered). A 422 is permanent.
        """
        quoted = urllib.parse.quote(event_id, safe="")
        body = json.dumps(payload).encode("utf-8")
        status, raw = self._request("POST", f"/api/internal/events/{quoted}/evidence", body=body)
        if status == 422:
            raise PermanentInternalError(f"evidence registration rejected with status {status}")
        if status != 200:
            raise InternalClientError(f"evidence registration failed with status {status}")
        data = _decode(raw)
        return EvidenceRegistrationResult(
            event_id=str(data.get("event_id") or event_id),
            media_type=str(data.get("media_type", "")),
            status=str(data.get("status", "")),
            retention_status=str(data.get("retention_status", "")),
            applied=bool(data.get("applied", False)),
        )

    # -- internals -----------------------------------------------------------------
    def _request(self, method: str, path: str, *, body: bytes | None = None) -> tuple[int, bytes]:
        url = f"{self._base}{path}"
        headers = {"Accept": "application/json", INTERNAL_TOKEN_HEADER: self.token}
        if body is not None:
            headers["Content-Type"] = "application/json"

        attempt = 0
        while True:
            try:
                status, payload = self.transport(method, url, headers, body, self.timeout)
            except OSError as exc:
                if attempt >= self.max_retries:
                    raise InternalClientError(str(exc)) from exc
                self._sleep_backoff(attempt)
                attempt += 1
                continue
            if (status in (408, 429) or 500 <= status < 600) and attempt < self.max_retries:
                self._sleep_backoff(attempt)
                attempt += 1
                continue
            return status, payload

    def _sleep_backoff(self, attempt: int) -> None:
        self.sleeper(min(self.retry_backoff_seconds * (2**attempt), 2.0))


def _decode(payload: bytes) -> dict[str, Any]:
    try:
        data = json.loads(payload.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError) as exc:
        raise InternalClientError("invalid JSON from backend") from exc
    if not isinstance(data, dict):
        raise InternalClientError("unexpected JSON payload from backend")
    return data
