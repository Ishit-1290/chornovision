"""Worker → backend internal client tests (OQ-09, D-12)."""

from __future__ import annotations

import json

import pytest

from vision.internal_client import (
    INTERNAL_TOKEN_HEADER,
    InternalClient,
    InternalClientError,
    PermanentInternalError,
)

TOKEN = "test-internal-token"


class Recorder:
    """A transport that replays scripted responses and records requests."""

    def __init__(self, responses: list[tuple[int, bytes] | BaseException]) -> None:
        self._responses = list(responses)
        self.requests: list[dict] = []
        self.slept: list[float] = []

    def __call__(self, method, url, headers, body, timeout):
        self.requests.append(
            {"method": method, "url": url, "headers": headers, "body": body, "timeout": timeout}
        )
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response

    def sleeper(self, seconds: float) -> None:
        self.slept.append(seconds)


def _client(transport: Recorder, **kwargs) -> InternalClient:
    return InternalClient(
        base_url="http://127.0.0.1:8000/",
        token=TOKEN,
        transport=transport,
        sleeper=transport.sleeper,
        **kwargs,
    )


def _json(payload: dict) -> tuple[int, bytes]:
    return 200, json.dumps(payload).encode("utf-8")


# --- plan -----------------------------------------------------------------------


def test_fetch_plan_parses_cameras_and_state() -> None:
    transport = Recorder(
        [
            _json(
                {
                    "monitoring_state": "running",
                    "cameras": [
                        {
                            "id": 1,
                            "name": "front",
                            "stream_reference": "rtsp://192.168.1.10:554/s",
                            "enabled": True,
                            "status": "stopped",
                        }
                    ],
                }
            )
        ]
    )
    plan = _client(transport).fetch_plan()

    assert plan.monitoring_state == "running"
    assert plan.running is True
    assert [camera.id for camera in plan.enabled_cameras()] == [1]
    request = transport.requests[0]
    assert request["url"] == "http://127.0.0.1:8000/api/internal/cameras"
    assert request["headers"][INTERNAL_TOKEN_HEADER] == TOKEN


def test_fetch_plan_excludes_disabled_cameras_from_enabled_list() -> None:
    transport = Recorder(
        [
            _json(
                {
                    "monitoring_state": "running",
                    "cameras": [
                        {
                            "id": 1,
                            "name": "a",
                            "stream_reference": "rtsp://x/1",
                            "enabled": False,
                            "status": "stopped",
                        }
                    ],
                }
            )
        ]
    )
    plan = _client(transport).fetch_plan()
    assert plan.enabled_cameras() == []


def test_fetch_plan_rejects_non_200() -> None:
    transport = Recorder([(503, b"{}")])
    with pytest.raises(InternalClientError):
        _client(transport, max_retries=0).fetch_plan()


def test_fetch_plan_parses_camera_configuration() -> None:
    transport = Recorder(
        [
            _json(
                {
                    "monitoring_state": "running",
                    "cameras": [
                        {
                            "id": 1,
                            "name": "front",
                            "stream_reference": "rtsp://192.168.1.10:554/s",
                            "enabled": True,
                            "status": "stopped",
                            "configuration": {"zones": [], "config_version": "2"},
                        }
                    ],
                }
            )
        ]
    )

    camera = _client(transport).fetch_plan().cameras[0]

    assert camera.configuration == {"zones": [], "config_version": "2"}


def test_fetch_plan_defaults_missing_configuration_to_empty() -> None:
    transport = Recorder(
        [
            _json(
                {
                    "monitoring_state": "running",
                    "cameras": [
                        {
                            "id": 1,
                            "name": "front",
                            "stream_reference": "rtsp://192.168.1.10:554/s",
                            "enabled": True,
                            "status": "stopped",
                        }
                    ],
                }
            )
        ]
    )

    assert _client(transport).fetch_plan().cameras[0].configuration == {}


def test_invalid_json_raises() -> None:
    transport = Recorder([(200, b"not-json")])
    with pytest.raises(InternalClientError):
        _client(transport, max_retries=0).fetch_plan()


# --- state reports --------------------------------------------------------------


def test_report_state_applied_true() -> None:
    transport = Recorder([_json({"camera_id": 1, "status": "active", "applied": True})])
    report = _client(transport).report_state(1, "active", metrics={"frames_processed": 5})
    assert report.applied is True
    assert report.status == "active"
    assert transport.requests[0]["method"] == "POST"
    assert transport.requests[0]["headers"]["Content-Type"] == "application/json"
    assert json.loads(transport.requests[0]["body"])["status"] == "active"


def test_report_state_conflict_returns_current_status() -> None:
    transport = Recorder(
        [(409, json.dumps({"detail": "illegal", "current_status": "connecting"}).encode())]
    )
    report = _client(transport).report_state(1, "degraded")
    assert report.applied is False
    assert report.status == "connecting"


def test_report_state_same_state_is_not_applied() -> None:
    transport = Recorder([_json({"camera_id": 1, "status": "active", "applied": False})])
    report = _client(transport).report_state(1, "active")
    assert report.applied is False
    assert report.status == "active"


def test_report_state_unexpected_status_raises() -> None:
    transport = Recorder([(500, b"{}")])
    with pytest.raises(InternalClientError):
        _client(transport, max_retries=0).report_state(1, "active")


# --- reconcile ------------------------------------------------------------------


def test_reconcile_returns_count() -> None:
    transport = Recorder([_json({"reconciled": 3})])
    assert _client(transport).reconcile() == 3
    assert transport.requests[0]["url"] == "http://127.0.0.1:8000/api/internal/reconcile"


def test_reconcile_rejects_non_200() -> None:
    transport = Recorder([(500, b"{}")])
    with pytest.raises(InternalClientError):
        _client(transport, max_retries=0).reconcile()


# --- retries --------------------------------------------------------------------


def test_server_errors_are_retried() -> None:
    transport = Recorder([(500, b"{}"), (500, b"{}"), _json({"reconciled": 1})])
    assert _client(transport, max_retries=3).reconcile() == 1
    assert len(transport.requests) == 3
    assert transport.slept  # backoff was applied


def test_transport_errors_are_retried_then_raise() -> None:
    transport = Recorder([OSError("connection refused"), OSError("connection refused")])
    with pytest.raises(InternalClientError):
        _client(transport, max_retries=1).reconcile()
    assert len(transport.requests) == 2


def test_no_retry_when_max_retries_is_zero() -> None:
    transport = Recorder([(500, b"{}")])
    with pytest.raises(InternalClientError):
        _client(transport, max_retries=0).reconcile()
    assert len(transport.requests) == 1


def test_base_url_trailing_slash_is_normalised() -> None:
    transport = Recorder([_json({"reconciled": 0})])
    _client(transport).reconcile()
    assert transport.requests[0]["url"] == "http://127.0.0.1:8000/api/internal/reconcile"


# --- event submissions (Phase 6) -------------------------------------------------


def _event_payload(event_id: str = "event-1") -> dict:
    return {"action": "opened", "event": {"event_id": event_id}}


def test_submit_event_posts_and_parses_the_result() -> None:
    transport = Recorder(
        [
            _json(
                {
                    "id": 3,
                    "event_id": "event-1",
                    "state_version": 2,
                    "status": "active",
                    "applied": True,
                }
            )
        ]
    )

    result = _client(transport).submit_event(_event_payload())

    assert result.event_id == "event-1"
    assert result.state_version == 2
    assert result.status == "active"
    assert result.applied is True
    request = transport.requests[0]
    assert request["method"] == "POST"
    assert request["url"] == "http://127.0.0.1:8000/api/internal/events"
    assert request["headers"][INTERNAL_TOKEN_HEADER] == TOKEN
    assert json.loads(request["body"])["event"]["event_id"] == "event-1"


def test_submit_event_duplicate_is_applied_false() -> None:
    transport = Recorder(
        [_json({"event_id": "event-1", "state_version": 1, "status": "active", "applied": False})]
    )

    assert _client(transport).submit_event(_event_payload()).applied is False


@pytest.mark.parametrize("status", [404, 422])
def test_submit_event_rejection_is_permanent(status: int) -> None:
    transport = Recorder([(status, b"{}")])
    with pytest.raises(PermanentInternalError):
        _client(transport, max_retries=0).submit_event(_event_payload())


def test_submit_event_server_error_is_retryable() -> None:
    transport = Recorder([(500, b"{}")])
    with pytest.raises(InternalClientError) as excinfo:
        _client(transport, max_retries=0).submit_event(_event_payload())
    assert not isinstance(excinfo.value, PermanentInternalError)


def test_submit_event_retries_transient_rate_limiting() -> None:
    transport = Recorder(
        [
            (429, b"{}"),
            _json({"event_id": "event-1", "state_version": 1, "status": "active", "applied": True}),
        ]
    )

    result = _client(transport, max_retries=1).submit_event(_event_payload())

    assert result.applied is True
    assert len(transport.requests) == 2
    assert transport.slept


# --- evidence registration (Phase 6) ---------------------------------------------


def test_register_evidence_quotes_the_event_id_in_the_path() -> None:
    transport = Recorder(
        [
            _json(
                {
                    "id": 1,
                    "event_id": "event/with space",
                    "media_type": "snapshot",
                    "status": "available",
                    "retention_status": "retained",
                    "applied": True,
                }
            )
        ]
    )

    result = _client(transport).register_evidence(
        "event/with space", {"event_id": "event/with space", "media_type": "snapshot"}
    )

    assert result.media_type == "snapshot"
    assert result.retention_status == "retained"
    assert (
        transport.requests[0]["url"]
        == "http://127.0.0.1:8000/api/internal/events/event%2Fwith%20space/evidence"
    )


def test_register_evidence_unknown_event_is_retryable() -> None:
    transport = Recorder([(404, b"{}")])
    with pytest.raises(InternalClientError) as excinfo:
        _client(transport, max_retries=0).register_evidence("event-1", {"event_id": "event-1"})
    assert not isinstance(excinfo.value, PermanentInternalError)


def test_register_evidence_invalid_payload_is_permanent() -> None:
    transport = Recorder([(422, b"{}")])
    with pytest.raises(PermanentInternalError):
        _client(transport, max_retries=0).register_evidence("event-1", {"event_id": "event-1"})
