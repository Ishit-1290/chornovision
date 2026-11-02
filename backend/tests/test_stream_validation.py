"""Tests for camera stream-address validation and SSRF defence (SEC-06)."""

from __future__ import annotations

import ipaddress
from urllib.parse import unquote, urlsplit

import pytest

from app.services.stream_validation import (
    METADATA_ADDRESSES,
    StreamValidationError,
    build_source_url,
    is_disallowed_address,
    pin_stream_host,
    redact_stream_reference,
    validate_stream_host,
    validate_stream_reference,
)

ALLOWED = frozenset({"rtsp", "rtsps"})


def validate(reference: str, **kwargs: object) -> str:
    kwargs.setdefault("allowed_schemes", ALLOWED)
    return validate_stream_reference(reference, **kwargs)  # type: ignore[arg-type]


# --- accepted -------------------------------------------------------------------


@pytest.mark.parametrize(
    "reference",
    [
        "rtsp://192.168.1.10:554/stream1",
        "rtsp://10.0.0.5/live",
        "rtsp://172.16.5.5/stream",
        "rtsps://camera.lan/stream",
        "rtsp://[fd00::1]/stream",  # IPv6 ULA (private) allowed by default
        "rtsp://camera.example.com/path?profile=main",
    ],
)
def test_accepts_lan_and_hostname_references(reference: str) -> None:
    assert validate(reference) == reference


def test_normalises_scheme_case() -> None:
    assert validate("RTSP://192.168.1.10/live") == "rtsp://192.168.1.10/live"


# --- schemes --------------------------------------------------------------------


@pytest.mark.parametrize(
    "reference",
    [
        "http://192.168.1.10/stream",
        "https://192.168.1.10/stream",
        "file:///etc/passwd",
        "ftp://192.168.1.10/stream",
        "gopher://127.0.0.1:6379/_INFO",
        "rtsp:/192.168.1.10",  # no authority
    ],
)
def test_rejects_disallowed_schemes(reference: str) -> None:
    with pytest.raises(StreamValidationError) as excinfo:
        validate(reference)
    assert excinfo.value.reason in {"unsupported_scheme", "missing_host"}


@pytest.mark.parametrize("reference", ["", "   ", "not a url", "192.168.1.10/stream"])
def test_rejects_missing_input(reference: str) -> None:
    with pytest.raises(StreamValidationError):
        validate(reference)


def test_rejects_embedded_credentials() -> None:
    with pytest.raises(StreamValidationError) as excinfo:
        validate("rtsp://admin:secret@192.168.1.10/stream")
    assert excinfo.value.reason == "embedded_credentials"


def test_rejects_user_only_credentials() -> None:
    with pytest.raises(StreamValidationError) as excinfo:
        validate("rtsp://admin@192.168.1.10/stream")
    assert excinfo.value.reason == "embedded_credentials"


# --- address policy -------------------------------------------------------------


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.1.2.3",
        "0.0.0.0",
        "169.254.169.254",  # cloud metadata (link-local)
        "224.0.0.1",  # multicast
        "240.0.0.1",  # reserved
        "255.255.255.255",
    ],
)
def test_rejects_disallowed_ipv4_destinations(host: str) -> None:
    with pytest.raises(StreamValidationError):
        validate(f"rtsp://{host}/stream")


@pytest.mark.parametrize(
    "host",
    [
        "::1",  # loopback
        "fe80::1",  # link-local
        "ff02::1",  # multicast
        "::",  # unspecified
        "::ffff:127.0.0.1",  # IPv4-mapped loopback
    ],
)
def test_rejects_disallowed_ipv6_destinations(host: str) -> None:
    with pytest.raises(StreamValidationError):
        validate(f"rtsp://[{host}]/stream")


def test_rejects_private_when_disallowed() -> None:
    with pytest.raises(StreamValidationError) as excinfo:
        validate("rtsp://192.168.1.10/stream", allow_private=False)
    assert excinfo.value.reason == "disallowed_address"


def test_allows_public_when_private_disallowed() -> None:
    assert validate("rtsp://93.184.216.34/stream", allow_private=False)


@pytest.mark.parametrize(
    "host",
    [
        "metadata.google.internal",
        "metadata",
        "instance-data.ec2.internal",
    ],
)
def test_rejects_metadata_hostnames(host: str) -> None:
    with pytest.raises(StreamValidationError) as excinfo:
        validate(f"rtsp://{host}/stream")
    assert excinfo.value.reason == "metadata_hostname"


def test_rejects_localhost_hostname() -> None:
    with pytest.raises(StreamValidationError) as excinfo:
        validate("rtsp://localhost/stream")
    assert excinfo.value.reason == "loopback_hostname"


@pytest.mark.parametrize(
    "reference",
    [
        "rtsp://bad_host!/stream",
        "rtsp://-leadinghyphen/stream",
        "rtsp://trailinghyphen-/stream",
        "rtsp://host:0/stream",
        "rtsp://host:70000/stream",
    ],
)
def test_rejects_invalid_hostnames_and_ports(reference: str) -> None:
    with pytest.raises(StreamValidationError):
        validate(reference)


# --- resolution (opt-in) --------------------------------------------------------


def test_resolution_rejects_disallowed_address() -> None:
    def resolver(host: str, port: int | None) -> set[str]:
        return {"127.0.0.1"}

    with pytest.raises(StreamValidationError) as excinfo:
        validate("rtsp://camera.lan/stream", resolve=True, resolver=resolver)
    assert excinfo.value.reason == "loopback address"


def test_resolution_accepts_public_address() -> None:
    def resolver(host: str, port: int | None) -> set[str]:
        return {"93.184.216.34"}

    assert validate("rtsp://camera.example.com/stream", resolve=True, resolver=resolver)


def test_resolution_failure_is_rejected() -> None:
    def resolver(host: str, port: int | None) -> set[str]:
        raise OSError("name or service not known")

    with pytest.raises(StreamValidationError) as excinfo:
        validate("rtsp://camera.lan/stream", resolve=True, resolver=resolver)
    assert excinfo.value.reason == "unresolvable"


def test_resolution_fails_closed_on_any_disallowed_address() -> None:
    def resolver(host: str, port: int | None) -> set[str]:
        return {"93.184.216.34", "10.0.0.1"}

    with pytest.raises(StreamValidationError):
        validate(
            "rtsp://camera.example.com/stream", resolve=True, resolver=resolver, allow_private=False
        )


# --- address classifier ---------------------------------------------------------


def test_is_disallowed_address_classification() -> None:
    assert is_disallowed_address("127.0.0.1", allow_private=True) == "loopback address"
    assert is_disallowed_address("::1", allow_private=True) == "loopback address"
    assert is_disallowed_address("10.0.0.1", allow_private=True) is None
    assert is_disallowed_address("10.0.0.1", allow_private=False) == "private address"
    assert is_disallowed_address("8.8.8.8", allow_private=False) is None


def test_metadata_addresses_are_denied_even_when_private_allowed() -> None:
    for address in METADATA_ADDRESSES:
        assert is_disallowed_address(address, allow_private=True) == "cloud metadata address"
    assert is_disallowed_address(ipaddress.ip_address("169.254.169.254"), allow_private=True)


# --- redaction ------------------------------------------------------------------


def test_redaction_strips_query_fragment_and_userinfo() -> None:
    redacted = redact_stream_reference("rtsp://admin:secret@192.168.1.10:554/live?token=abc#frag")
    assert redacted == "rtsp://192.168.1.10:554/live"
    assert "secret" not in redacted
    assert "token" not in redacted
    assert "abc" not in redacted


def test_redaction_keeps_ipv6_brackets() -> None:
    assert redact_stream_reference("rtsp://[fd00::1]:554/live") == "rtsp://[fd00::1]:554/live"


# --- credential injection (gateway source URLs) ---------------------------------


def test_build_source_url_percent_encodes_credentials() -> None:
    url = build_source_url(
        "rtsp://192.168.1.10:554/live?profile=main", "user@corp", "p:a/ss?#% word"
    )
    parts = urlsplit(url)
    # The userinfo is a single percent-encoded unit, so no structural character leaks.
    assert parts.hostname == "192.168.1.10"
    assert parts.port == 554
    assert parts.path == "/live"
    assert parts.query == "profile=main"
    assert "@" not in parts.netloc.split("@", 1)[0]
    userinfo = parts.netloc.rsplit("@", 1)[0]
    username, _, password = userinfo.partition(":")
    assert unquote(username) == "user@corp"
    assert unquote(password) == "p:a/ss?#% word"


def test_build_source_url_rejects_missing_host() -> None:
    with pytest.raises(StreamValidationError):
        build_source_url("rtsp:///nohost", "user", "pass")


def test_build_source_url_keeps_ipv6_brackets() -> None:
    url = build_source_url("rtsp://[fd00::1]:554/live", "user", "pass")
    assert url == "rtsp://user:pass@[fd00::1]:554/live"


# --- host validation / pinning --------------------------------------------------


def test_pin_stream_host_replaces_hostname_with_validated_ip() -> None:
    def resolver(host: str, port: int | None) -> set[str]:
        assert host == "camera.lan"
        return {"10.0.0.7"}

    pinned = pin_stream_host("rtsp://camera.lan:8554/stream?x=1", resolver=resolver)
    assert pinned == "rtsp://10.0.0.7:8554/stream?x=1"


def test_pin_stream_host_fails_closed_on_disallowed_address() -> None:
    def resolver(host: str, port: int | None) -> set[str]:
        return {"93.184.216.34", "127.0.0.1"}

    with pytest.raises(StreamValidationError) as excinfo:
        pin_stream_host("rtsp://camera.lan/stream", resolver=resolver)
    assert "loopback" in excinfo.value.reason


def test_pin_stream_host_accepts_ip_literal_without_resolving() -> None:
    called = False

    def resolver(host: str, port: int | None) -> set[str]:
        nonlocal called
        called = True
        return set()

    assert pin_stream_host("rtsp://10.1.2.3/live", resolver=resolver) == "rtsp://10.1.2.3/live"
    assert called is False


def test_pin_stream_host_rejects_disallowed_ip_literal() -> None:
    with pytest.raises(StreamValidationError):
        pin_stream_host("rtsp://169.254.169.254/live")


def test_validate_stream_host_resolves_and_rejects() -> None:
    def loopback(host: str, port: int | None) -> set[str]:
        return {"127.0.0.1"}

    with pytest.raises(StreamValidationError):
        validate_stream_host("rtsps://camera.lan/stream", resolver=loopback)

    def allowed(host: str, port: int | None) -> set[str]:
        return {"93.184.216.34"}

    # A valid host validates without rewriting the reference.
    assert validate_stream_host("rtsps://camera.lan/stream", resolver=allowed) is None


def test_validate_stream_host_rejects_metadata_and_localhost() -> None:
    assert pytest.raises(
        StreamValidationError, validate_stream_host, "rtsp://metadata.google.internal/x"
    )
    assert pytest.raises(StreamValidationError, validate_stream_host, "rtsp://localhost/x")
