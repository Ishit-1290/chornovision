"""Camera stream-address validation and SSRF defence (SEC-06, G §15.5).

Camera stream references are untrusted input: an authenticated administrator (or a
compromised browser session) could otherwise make the backend/worker connect to
internal or cloud-metadata endpoints. This module validates a reference *without*
opening any connection.

Policy (see Decision D-21):

- Only the configured schemes (default ``rtsp``/``rtsps``) are accepted; ``http(s)``,
  ``file``, ``ftp``, ``gopher``, and every other scheme are rejected.
- Embedded credentials (``user:pass@host``) are rejected, so credentials are never
  stored or echoed.
- The destination must be a resolvable **host** and must not be loopback, link-local
  (which includes the ``169.254.169.254`` cloud-metadata address), multicast,
  reserved, unspecified, or a known metadata hostname.
- Private ranges (RFC1918 / IPv6 ULA) are allowed by default because cameras normally
  live on the local network, and can be forbidden with
  ``CAMERA_ALLOW_PRIVATE_NETWORKS=false``.

DNS-rebinding note. Hostname resolution at configuration time is **not** authoritative
(the name can resolve differently, or be rebound, before a connection is opened), so it
is disabled by default. :func:`validate_stream_reference` implements the address checks,
including an opt-in resolving path used by tests; the authoritative check is performed at
connection time by the vision worker (``vision/net.py``, D-28): resolve, verify every
returned address with :func:`is_disallowed_address`, then **pin** the validated address for
the connection. Redirect-following to a different, unvalidated address is refused.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from collections.abc import Callable, Collection, Iterable
from urllib.parse import quote, urlsplit, urlunsplit

from app.config import get_settings

#: Hostnames that are always rejected regardless of ``allow_private``.
METADATA_HOSTNAMES: frozenset[str] = frozenset(
    {
        "metadata",
        "metadata.google.internal",
        "metadata.goog",
        "instance-data",
        "instance-data.ec2.internal",
    }
)

#: Addresses used to expose cloud-instance credentials; rejected even when private
#: networks are allowed.
METADATA_ADDRESSES: frozenset[ipaddress.IPv4Address | ipaddress.IPv6Address] = frozenset(
    {
        ipaddress.ip_address("169.254.169.254"),  # AWS/GCP/Azure IMDS (also link-local)
        ipaddress.ip_address("fd00:ec2::254"),  # AWS IMDS over IPv6 (also ULA)
    }
)

_LABEL_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")

Resolver = Callable[[str, int | None], Iterable[str]]


class StreamValidationError(ValueError):
    """A stream reference was rejected. ``reason`` is a short machine-readable code."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def default_resolver(host: str, port: int | None) -> set[str]:
    """Resolve ``host`` to a set of IP-address strings using the system resolver."""
    infos = socket.getaddrinfo(host, port or 0, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    return {info[4][0] for info in infos}


def is_disallowed_address(
    address: ipaddress.IPv4Address | ipaddress.IPv6Address | str,
    *,
    allow_private: bool,
) -> str | None:
    """Return a rejection reason for ``address``, or ``None`` if it is acceptable.

    IPv4-mapped IPv6 addresses are unwrapped first so that ``::ffff:127.0.0.1`` cannot
    bypass the loopback check.
    """
    ip = ipaddress.ip_address(address) if isinstance(address, str) else address
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if ip in METADATA_ADDRESSES:
        return "cloud metadata address"
    if ip.is_unspecified:
        return "unspecified address"
    if ip.is_loopback:
        return "loopback address"
    if ip.is_link_local:
        return "link-local address"
    if ip.is_multicast:
        return "multicast address"
    if ip.is_reserved:
        return "reserved address"
    if not allow_private and ip.is_private:
        return "private address"
    return None


def _validate_hostname_syntax(host: str) -> None:
    candidate = host[:-1] if host.endswith(".") else host
    if not candidate or len(candidate) > 253:
        raise StreamValidationError("invalid_hostname", "host name is empty or too long")
    try:
        candidate.encode("ascii")
    except UnicodeEncodeError as exc:
        raise StreamValidationError(
            "invalid_hostname", "host name must be ASCII (use a punycode form)"
        ) from exc
    for label in candidate.split("."):
        if not _LABEL_RE.match(label):
            raise StreamValidationError("invalid_hostname", "host name has an invalid label")


def _check_resolved_addresses(
    host: str,
    port: int | None,
    *,
    allow_private: bool,
    resolver: Resolver,
) -> None:
    try:
        addresses = list(resolver(host, port))
    except OSError as exc:
        raise StreamValidationError("unresolvable", "host name could not be resolved") from exc
    if not addresses:
        raise StreamValidationError("unresolvable", "host name resolved to no addresses")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise StreamValidationError(
                "invalid_address", "resolver returned an invalid address"
            ) from exc
        reason = is_disallowed_address(ip, allow_private=allow_private)
        if reason is not None:
            raise StreamValidationError(reason, f"stream host resolves to a {reason}")


def validate_stream_reference(
    reference: str,
    *,
    allowed_schemes: Collection[str] | None = None,
    allow_private: bool = True,
    resolve: bool = False,
    resolver: Resolver = default_resolver,
) -> str:
    """Validate and normalise a camera stream reference, or raise.

    Returns the normalised URL (lower-cased scheme, no userinfo) on success.
    """
    schemes = (
        frozenset(allowed_schemes)
        if allowed_schemes is not None
        else get_settings().allowed_stream_schemes
    )
    text = reference.strip()
    if not text:
        raise StreamValidationError("empty", "stream reference must not be empty")
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*:", text):
        raise StreamValidationError("missing_scheme", "stream reference must include a URL scheme")
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError as exc:
        raise StreamValidationError("invalid_url", "stream reference is not a valid URL") from exc

    scheme = parts.scheme.lower()
    if scheme not in schemes:
        allowed = ", ".join(sorted(schemes)) or "(none configured)"
        raise StreamValidationError(
            "unsupported_scheme",
            f"scheme {scheme!r} is not allowed (allowed: {allowed})",
        )
    if parts.username or parts.password:
        raise StreamValidationError(
            "embedded_credentials",
            "stream reference must not embed credentials",
        )

    host = parts.hostname
    if not host:
        raise StreamValidationError("missing_host", "stream reference must include a host")
    if port is not None and not 1 <= port <= 65535:
        raise StreamValidationError("invalid_port", "stream reference port is out of range")

    host = host.lower()
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        _validate_hostname_syntax(host)
        if host.rstrip(".") in METADATA_HOSTNAMES:
            raise StreamValidationError(
                "metadata_hostname", "stream host is a known cloud metadata hostname"
            ) from None
        if host.rstrip(".") == "localhost" or host.rstrip(".").endswith(".localhost"):
            raise StreamValidationError("loopback_hostname", "stream host is loopback") from None
        if resolve:
            _check_resolved_addresses(host, port, allow_private=allow_private, resolver=resolver)
    else:
        reason = is_disallowed_address(literal, allow_private=allow_private)
        if reason is not None:
            raise StreamValidationError("disallowed_address", f"stream host is a {reason}")

    # Rebuild without userinfo so the stored value can never carry credentials.
    host_display = f"[{host}]" if ":" in host else host
    netloc = f"{host_display}:{port}" if port is not None else host_display
    return urlunsplit((scheme, netloc, parts.path, parts.query, parts.fragment))


def redact_stream_reference(reference: str) -> str:
    """Return a response-safe form of a stream reference.

    Userinfo, query string, and fragment are removed because they may carry secrets
    (for example a signed-token query parameter); scheme, host, port, and path remain.
    """
    try:
        parts = urlsplit(reference)
    except ValueError:
        return "<redacted>"
    host = parts.hostname
    if not host:
        return "<redacted>"
    host_display = f"[{host}]" if ":" in host else host
    netloc = f"{host_display}:{parts.port}" if parts.port is not None else host_display
    return urlunsplit((parts.scheme.lower(), netloc, parts.path, "", ""))


def build_source_url(reference: str, username: str, password: str) -> str:
    """Inject a credential pair into an already-validated stream reference.

    The username and password are percent-encoded as a single userinfo unit, so characters
    such as ``@``, ``:``, ``/``, ``?``, ``#``, ``%`` and non-ASCII text cannot break the URL
    or smuggle additional URL components. This is the only place a credential-bearing URL is
    constructed; the result must go straight to the streaming gateway and never to a log,
    API response, or exception message.
    """
    parts = urlsplit(reference)
    host = parts.hostname
    if not host:
        raise StreamValidationError("missing_host", "stream reference must include a host")
    host_display = f"[{host}]" if ":" in host else host
    userinfo = f"{quote(username, safe='')}:{quote(password, safe='')}"
    netloc = f"{userinfo}@{host_display}"
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def validate_stream_host(
    reference: str,
    *,
    allow_private: bool = True,
    resolver: Resolver = default_resolver,
) -> None:
    """Resolve ``reference``'s host and validate **every** returned address.

    Use this when the destination cannot be rewritten to an IP literal (for example
    ``rtsps`` with hostname-based TLS verification). It fails closed if any address is
    prohibited. Re-resolution by the consumer remains a documented residual, so callers
    should prefer :func:`pin_stream_host`.
    """
    parts = urlsplit(reference)
    host = parts.hostname
    if not host:
        raise StreamValidationError("missing_host", "stream reference must include a host")
    host = host.lower()
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        _validate_hostname_syntax(host)
        if host.rstrip(".") in METADATA_HOSTNAMES:
            raise StreamValidationError(
                "metadata_hostname", "stream host is a known cloud metadata hostname"
            ) from None
        if host.rstrip(".") == "localhost" or host.rstrip(".").endswith(".localhost"):
            raise StreamValidationError("loopback_hostname", "stream host is loopback") from None
        _check_resolved_addresses(host, parts.port, allow_private=allow_private, resolver=resolver)
        return
    reason = is_disallowed_address(literal, allow_private=allow_private)
    if reason is not None:
        raise StreamValidationError("disallowed_address", f"stream host is a {reason}")


def pin_stream_host(
    reference: str,
    *,
    allow_private: bool = True,
    resolver: Resolver = default_resolver,
) -> str:
    """Resolve, validate, and replace the host with a validated IP literal.

    This mirrors the vision worker's connection-time enforcement (D-28) for the streaming
    gateway, which otherwise performs its own DNS resolution and could therefore be redirected
    by a rebinding hostname. Every resolved address is validated (fail closed) and one is
    pinned; the scheme, port, path, and query are preserved.
    """
    parts = urlsplit(reference)
    host = parts.hostname
    if not host:
        raise StreamValidationError("missing_host", "stream reference must include a host")
    host = host.lower()
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        _validate_hostname_syntax(host)
        if host.rstrip(".") in METADATA_HOSTNAMES:
            raise StreamValidationError(
                "metadata_hostname", "stream host is a known cloud metadata hostname"
            ) from None
        if host.rstrip(".") == "localhost" or host.rstrip(".").endswith(".localhost"):
            raise StreamValidationError("loopback_hostname", "stream host is loopback") from None
        try:
            addresses = list(resolver(host, parts.port))
        except OSError as exc:
            raise StreamValidationError("unresolvable", "host name could not be resolved") from exc
        if not addresses:
            raise StreamValidationError(
                "unresolvable", "host name resolved to no addresses"
            ) from None
        validated: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        for address in addresses:
            try:
                candidate = ipaddress.ip_address(address)
            except ValueError as exc:
                raise StreamValidationError(
                    "invalid_address", "resolver returned an invalid address"
                ) from exc
            reason = is_disallowed_address(candidate, allow_private=allow_private)
            if reason is not None:
                raise StreamValidationError(reason, f"stream host resolves to a {reason}") from None
            validated.append(candidate)
        pinned = validated[0]
    else:
        reason = is_disallowed_address(literal, allow_private=allow_private)
        if reason is not None:
            raise StreamValidationError("disallowed_address", f"stream host is a {reason}")
        pinned = literal

    host_display = f"[{pinned}]" if isinstance(pinned, ipaddress.IPv6Address) else str(pinned)
    netloc = f"{host_display}:{parts.port}" if parts.port is not None else host_display
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
