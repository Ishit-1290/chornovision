"""Connection-time SSRF enforcement for camera streams (SEC-06, D-22, OQ-14).

Phase 3 validated stream references at *configuration* time but explicitly deferred the
authoritative, connection-time check to this phase because a one-off hostname lookup
cannot defeat DNS rebinding. This module performs the authoritative check **immediately
before a connection is opened** and produces a *pinned* URL whose host is a validated IP
literal, so the decoder (OpenCV/FFmpeg) never resolves the hostname itself.

Policy (identical to ``app.services.stream_validation`` — single source of truth):

- Scheme allow-list (default ``rtsp``/``rtsps``); embedded credentials rejected.
- Resolve the hostname; validate **every** returned address against the destination
  policy (loopback / link-local / multicast / reserved / unspecified / cloud-metadata
  always rejected; private RFC1918/ULA subject to ``CAMERA_ALLOW_PRIVATE_NETWORKS``).
- Reject the connection if **any** candidate address is disallowed (fail closed), then
  pin one validated address.

Residual risk (documented, not hidden): in ``HOSTNAME`` host mode the original hostname
is preserved in the URL, so the decoder re-resolves independently and DNS rebinding is
**not** defeated. ``PIN`` (the default) is the enforceable mode and is what satisfies the
Phase 4 requirement that "the actual socket destination is the validated address".

This module never opens a connection and never logs stream references or credentials.
"""

from __future__ import annotations

import dataclasses
import ipaddress
from collections.abc import Collection
from urllib.parse import urlsplit, urlunsplit

from app.services.stream_validation import (
    Resolver,
    StreamValidationError,
    default_resolver,
    is_disallowed_address,
    validate_stream_reference,
)

from vision.config import StreamHostMode

#: Default transport ports per scheme when the reference omits a port.
DEFAULT_PORTS: dict[str, int] = {"rtsp": 554, "rtsps": 322}


class StreamSecurityError(Exception):
    """A stream reference was rejected at connection time.

    ``reason`` is a short, machine-readable code (no stream contents).
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclasses.dataclass(frozen=True)
class PinnedTarget:
    """A validated, connection-ready stream target.

    ``url`` is what the decoder must be given. In ``PIN`` mode its host is ``address``
    (a validated IP literal), so no further DNS resolution can occur.
    """

    scheme: str
    original_host: str
    port: int
    address: str
    url: str
    pinned: bool

    @property
    def safe_display(self) -> str:
        """A credential-free, query-free string safe to log."""
        host = f"[{self.address}]" if ":" in self.address else self.address
        return f"{self.scheme}://{host}:{self.port}"


def _build_url(scheme: str, host: str, port: int, path: str, query: str) -> str:
    host_display = f"[{host}]" if ":" in host else host
    netloc = f"{host_display}:{port}"
    return urlunsplit((scheme, netloc, path, query, ""))


def resolve_and_validate(
    reference: str,
    *,
    allowed_schemes: Collection[str],
    allow_private: bool,
    host_mode: StreamHostMode = StreamHostMode.PIN,
    resolver: Resolver = default_resolver,
) -> PinnedTarget:
    """Validate ``reference`` at connection time and return a pinned target.

    Raises :class:`StreamSecurityError` when the reference is unsafe or unresolvable.
    """
    try:
        normalized = validate_stream_reference(
            reference,
            allowed_schemes=allowed_schemes,
            allow_private=allow_private,
            resolve=False,  # resolution is performed here, authoritatively
        )
    except StreamValidationError as exc:
        raise StreamSecurityError(exc.reason, str(exc)) from exc

    parts = urlsplit(normalized)
    scheme = parts.scheme.lower()
    host = parts.hostname or ""
    port = parts.port or DEFAULT_PORTS.get(scheme, 554)

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        # Hostname: resolve *now* and validate every candidate address.
        try:
            candidates = list(resolver(host, port))
        except OSError as exc:
            raise StreamSecurityError("unresolvable", "stream host could not be resolved") from exc
        if not candidates:
            raise StreamSecurityError(
                "unresolvable", "stream host resolved to no addresses"
            ) from None
        validated: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        for candidate in candidates:
            try:
                ip = ipaddress.ip_address(candidate)
            except ValueError as exc:
                raise StreamSecurityError(
                    "invalid_address", "resolver returned an invalid address"
                ) from exc
            reason = is_disallowed_address(ip, allow_private=allow_private)
            if reason is not None:
                # Fail closed: one bad address rejects the whole host.
                raise StreamSecurityError(reason, f"stream host resolves to a {reason}") from None
            validated.append(ip)
        # Deterministic choice: prefer IPv4, then lowest address.
        validated.sort(key=lambda ip: (ip.version != 4, ip))
        address = str(validated[0])
    else:
        reason = is_disallowed_address(literal, allow_private=allow_private)
        if reason is not None:
            raise StreamSecurityError(reason, f"stream host is a {reason}")
        address = str(literal)

    if host_mode is StreamHostMode.HOSTNAME:
        pinned_url = _build_url(scheme, host, port, parts.path, parts.query)
        pinned = False
    else:
        pinned_url = _build_url(scheme, address, port, parts.path, parts.query)
        pinned = True

    return PinnedTarget(
        scheme=scheme,
        original_host=host,
        port=port,
        address=address,
        url=pinned_url,
        pinned=pinned,
    )
