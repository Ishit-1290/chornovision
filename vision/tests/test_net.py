"""Connection-time SSRF enforcement tests (SEC-06, D-22, OQ-14)."""

from __future__ import annotations

import pytest

from vision.config import StreamHostMode
from vision.net import StreamSecurityError, resolve_and_validate

SCHEMES = frozenset({"rtsp", "rtsps"})


def resolve(host: str, port: int | None):
    """Placeholder resolver; individual tests pass their own."""


def resolver_returning(*addresses: str):
    def _resolve(host: str, port: int | None) -> list[str]:
        return list(addresses)

    return _resolve


def _validate(reference: str, *, allow_private: bool = True, resolver=resolve, mode=None):
    kwargs = {
        "allowed_schemes": SCHEMES,
        "allow_private": allow_private,
        "resolver": resolver,
    }
    if mode is not None:
        kwargs["host_mode"] = mode
    return resolve_and_validate(reference, **kwargs)


# --- scheme / credentials -------------------------------------------------------


def test_unsupported_scheme_is_rejected() -> None:
    with pytest.raises(StreamSecurityError) as excinfo:
        _validate("http://camera.example.com/stream")
    assert excinfo.value.reason == "unsupported_scheme"


def test_embedded_credentials_are_rejected() -> None:
    with pytest.raises(StreamSecurityError) as excinfo:
        _validate("rtsp://user:secret@camera.example.com/stream")
    assert excinfo.value.reason == "embedded_credentials"


def test_missing_scheme_is_rejected() -> None:
    with pytest.raises(StreamSecurityError) as excinfo:
        _validate("camera.example.com/stream")
    assert excinfo.value.reason == "missing_scheme"


# --- literals -------------------------------------------------------------------


@pytest.mark.parametrize(
    "reference",
    [
        "rtsp://127.0.0.1:554/stream1",
        "rtsp://0.0.0.0:554/stream1",
        "rtsp://169.254.169.254/latest/meta-data",
        "rtsp://[::1]:554/stream1",
        "rtsp://[::ffff:127.0.0.1]:554/stream1",
    ],
)
def test_disallowed_literals_are_rejected(reference: str) -> None:
    with pytest.raises(StreamSecurityError):
        _validate(reference)


def test_cloud_metadata_hostname_is_rejected() -> None:
    with pytest.raises(StreamSecurityError) as excinfo:
        _validate("rtsp://metadata.google.internal/computeMetadata/v1/")
    assert excinfo.value.reason == "metadata_hostname"


def test_localhost_hostname_is_rejected() -> None:
    with pytest.raises(StreamSecurityError):
        _validate("rtsp://localhost:554/stream1")


def test_loopback_is_rejected_even_when_private_allowed() -> None:
    with pytest.raises(StreamSecurityError):
        _validate("rtsp://127.0.0.1:554/stream1", allow_private=True)


def test_private_literal_allowed_when_policy_permits() -> None:
    target = _validate("rtsp://192.168.1.10:554/stream1")
    assert target.address == "192.168.1.10"
    assert target.pinned is True


def test_private_literal_rejected_when_policy_forbids() -> None:
    with pytest.raises(StreamSecurityError) as excinfo:
        _validate("rtsp://192.168.1.10:554/stream1", allow_private=False)
    assert excinfo.value.reason == "disallowed_address"


# --- hostname resolution: fail-closed and pinning -------------------------------


def test_hostname_is_resolved_and_validated() -> None:
    target = _validate(
        "rtsp://camera.example.com:554/stream1",
        resolver=resolver_returning("192.168.1.10"),
    )
    assert target.address == "192.168.1.10"
    assert target.original_host == "camera.example.com"
    assert target.pinned is True
    assert target.url == "rtsp://192.168.1.10:554/stream1"


def test_pinned_url_never_contains_the_hostname() -> None:
    target = _validate(
        "rtsp://camera.example.com/stream1",
        resolver=resolver_returning("192.168.1.10"),
    )
    assert "camera.example.com" not in target.url
    assert target.address in target.url


def test_hostname_resolving_to_disallowed_address_is_rejected() -> None:
    with pytest.raises(StreamSecurityError) as excinfo:
        _validate("rtsp://camera.example.com/stream1", resolver=resolver_returning("127.0.0.1"))
    assert excinfo.value.reason == "loopback address"


def test_any_disallowed_candidate_rejects_the_whole_host() -> None:
    # Fail closed: one bad address among good ones rejects the host.
    with pytest.raises(StreamSecurityError) as excinfo:
        _validate(
            "rtsp://camera.example.com/stream1",
            resolver=resolver_returning("192.168.1.10", "127.0.0.1"),
        )
    assert excinfo.value.reason == "loopback address"


def test_dns_rebinding_cannot_redirect_a_pinned_target() -> None:
    calls = {"count": 0}

    def rebinding_resolver(host: str, port: int | None) -> list[str]:
        calls["count"] += 1
        # First lookup is benign; a later lookup (rebinding) points at loopback.
        return ["192.168.1.10"] if calls["count"] == 1 else ["127.0.0.1"]

    target = _validate("rtsp://camera.example.com/stream1", resolver=rebinding_resolver)
    # The decoder only ever sees the validated literal, so it cannot re-resolve.
    assert target.address == "192.168.1.10"
    assert target.url == "rtsp://192.168.1.10:554/stream1"

    with pytest.raises(StreamSecurityError):
        _validate("rtsp://camera.example.com/stream1", resolver=rebinding_resolver)


def test_unresolvable_host_raises() -> None:
    def failing(host: str, port: int | None):
        raise OSError("name resolution failed")

    with pytest.raises(StreamSecurityError) as excinfo:
        _validate("rtsp://camera.example.com/stream1", resolver=failing)
    assert excinfo.value.reason == "unresolvable"


def test_empty_resolution_raises() -> None:
    with pytest.raises(StreamSecurityError) as excinfo:
        _validate("rtsp://camera.example.com/stream1", resolver=resolver_returning())
    assert excinfo.value.reason == "unresolvable"


def test_resolver_returning_invalid_address_raises() -> None:
    with pytest.raises(StreamSecurityError) as excinfo:
        _validate("rtsp://camera.example.com/stream1", resolver=resolver_returning("not-an-ip"))
    assert excinfo.value.reason == "invalid_address"


# --- host modes and defaults ----------------------------------------------------


def test_hostname_mode_preserves_hostname_and_is_not_pinned() -> None:
    target = _validate(
        "rtsp://camera.example.com/stream1",
        resolver=resolver_returning("192.168.1.10"),
        mode=StreamHostMode.HOSTNAME,
    )
    assert target.pinned is False
    assert "camera.example.com" in target.url
    assert target.address == "192.168.1.10"


def test_default_port_is_applied_per_scheme() -> None:
    rtsp = _validate("rtsp://camera.example.com/stream1", resolver=resolver_returning("10.0.0.5"))
    rtsps = _validate("rtsps://camera.example.com/stream1", resolver=resolver_returning("10.0.0.5"))
    assert rtsp.port == 554
    assert rtsps.port == 322
    assert rtsp.url == "rtsp://10.0.0.5:554/stream1"
    assert rtsps.url == "rtsps://10.0.0.5:322/stream1"


def test_explicit_port_is_preserved() -> None:
    target = _validate(
        "rtsp://camera.example.com:8554/live", resolver=resolver_returning("10.0.0.5")
    )
    assert target.port == 8554
    assert target.url == "rtsp://10.0.0.5:8554/live"


def test_query_string_is_preserved_but_credentials_are_not_present() -> None:
    target = _validate(
        "rtsp://camera.example.com/stream?channel=1",
        resolver=resolver_returning("10.0.0.5"),
    )
    assert target.url == "rtsp://10.0.0.5:554/stream?channel=1"


def test_safe_display_has_no_credentials_or_query() -> None:
    target = _validate(
        "rtsp://camera.example.com/stream?token=secret",
        resolver=resolver_returning("10.0.0.5"),
    )
    assert target.safe_display == "rtsp://10.0.0.5:554"
    assert "secret" not in target.safe_display


def test_ipv6_literal_is_bracketed_in_url_and_display() -> None:
    target = _validate("rtsp://[fd00::1]:554/stream1")
    assert target.address == "fd00::1"
    assert target.url == "rtsp://[fd00::1]:554/stream1"
    assert target.safe_display == "rtsp://[fd00::1]:554"


def test_resolved_addresses_prefer_ipv4() -> None:
    target = _validate(
        "rtsp://camera.example.com/stream1",
        resolver=resolver_returning("fd00::1", "192.168.1.10"),
    )
    assert target.address == "192.168.1.10"
