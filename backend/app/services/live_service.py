"""Live-playback orchestration (Phase 10; FR-51, D-62/D-63/D-65).

The analysis path (vision worker) and the viewing path (browser -> MediaMTX -> camera) stay
independent. This module only describes and registers the *viewing* path:

* Playback is opt-in (``LIVE_PLAYBACK_ENABLED`` + gateway URLs); deploying MediaMTX alone
  never makes the dashboard playable.
* The camera source is validated and, when possible, pinned to a validated IP literal before
  it is handed to the gateway, so the gateway cannot be used as an SSRF hop.
* A gateway failure degrades only live playback. Camera CRUD, monitoring, events, and evidence
  are never affected: every gateway call here is best-effort and non-raising for those paths.
"""

from __future__ import annotations

import ipaddress
import logging
from urllib.parse import urlsplit

from app.config import get_settings
from app.models.camera import Camera
from app.schemas.live import LivePlaybackInfo
from app.services.credential_cipher import CredentialError, decrypt_credentials
from app.services.live_gateway import GatewayError, GatewayPathStatus, LiveGateway
from app.services.stream_validation import (
    StreamValidationError,
    build_source_url,
    pin_stream_host,
    validate_stream_host,
)

logger = logging.getLogger(__name__)


def _gateway() -> LiveGateway:
    return LiveGateway(get_settings())


def _hostname_is_ip_literal(host: str | None) -> bool:
    if not host:
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def gateway_source_url(camera: Camera) -> str:
    """Build the URL handed to the gateway for ``camera``.

    The URL may contain credentials and is therefore **never** returned or logged. It is
    computed on demand from the stored (validated) reference plus the encrypted credential
    pair.
    """
    settings = get_settings()
    reference = camera.stream_reference
    parts = urlsplit(reference)
    scheme = parts.scheme.lower()

    # Pin the host for plain RTSP. For RTSPS with a hostname, pinning would break TLS
    # certificate/SNI verification, so resolve+validate without rewriting and document the
    # residual (the same trade-off as VISION_STREAM_HOST_MODE=hostname, D-28).
    if settings.live_gateway_pin_hosts and not (
        scheme == "rtsps" and not _hostname_is_ip_literal(parts.hostname)
    ):
        reference = pin_stream_host(reference, allow_private=settings.camera_allow_private_networks)
    else:
        validate_stream_host(reference, allow_private=settings.camera_allow_private_networks)

    if camera.stream_credentials_encrypted:
        username, password = decrypt_credentials(camera.stream_credentials_encrypted)
        return build_source_url(reference, username, password)
    return reference


def _info_from_status(
    camera: Camera, gateway: LiveGateway, status: GatewayPathStatus
) -> LivePlaybackInfo:
    if status.online or status.ready:
        state = "live"
    elif status.registered and status.readers > 0:
        # A viewer is attached but the source is not producing: genuinely disconnected.
        state = "disconnected"
    else:
        state = "connecting"
    return LivePlaybackInfo(
        available=True,
        state=state,
        protocol="webrtc",
        path=gateway.path_name(camera.id),
        whep_url=gateway.whep_url(camera.id),
    )


def _precondition_error(camera: Camera) -> LivePlaybackInfo | None:
    settings = get_settings()
    if not settings.live_playback_enabled:
        return LivePlaybackInfo(
            available=False,
            state="unavailable",
            detail="live playback is not configured",
        )
    if not camera.enabled:
        return LivePlaybackInfo(
            available=False,
            state="unavailable",
            detail="camera is disabled",
        )
    return None


def playback_status(camera: Camera) -> LivePlaybackInfo:
    """Read-only live-playback status (no gateway mutation)."""
    blocked = _precondition_error(camera)
    if blocked is not None:
        return blocked
    gateway = _gateway()
    try:
        status = gateway.path_status(camera.id)
    except GatewayError as exc:
        return LivePlaybackInfo(
            available=False,
            state="unavailable",
            detail=f"streaming gateway unavailable ({exc.reason})",
        )
    return _info_from_status(camera, gateway, status)


def start_playback(camera: Camera) -> LivePlaybackInfo:
    """Ensure the gateway path exists, then report playback status.

    Idempotent: repeated calls refresh the same stable path rather than creating duplicates.
    """
    blocked = _precondition_error(camera)
    if blocked is not None:
        return blocked

    try:
        source = gateway_source_url(camera)
    except CredentialError:
        return LivePlaybackInfo(
            available=False,
            state="error",
            detail="stored camera credentials are unavailable",
        )
    except StreamValidationError as exc:
        return LivePlaybackInfo(
            available=False,
            state="error",
            detail=f"camera source rejected ({exc.reason})",
        )

    gateway = _gateway()
    try:
        gateway.ensure_path(camera.id, source)
    except GatewayError as exc:
        return LivePlaybackInfo(
            available=False,
            state="unavailable",
            detail=f"streaming gateway unavailable ({exc.reason})",
        )
    try:
        status = gateway.path_status(camera.id)
    except GatewayError as exc:
        return LivePlaybackInfo(
            available=False,
            state="unavailable",
            detail=f"streaming gateway unavailable ({exc.reason})",
        )
    return _info_from_status(camera, gateway, status)


def on_camera_changed(camera: Camera) -> None:
    """Best-effort gateway registration after a camera is created or updated.

    Never raises: a gateway outage must not fail camera management.
    """
    settings = get_settings()
    if not settings.live_playback_enabled:
        return
    if not camera.enabled:
        remove_camera(camera)
        return
    try:
        _gateway().ensure_path(camera.id, gateway_source_url(camera))
    except (GatewayError, StreamValidationError, CredentialError) as exc:
        reason = getattr(exc, "reason", "error")
        logger.warning("live playback registration skipped for camera %s (%s)", camera.id, reason)


def remove_camera(camera: Camera) -> None:
    """Best-effort gateway cleanup when a camera is disabled or retired."""
    settings = get_settings()
    if not settings.live_playback_enabled:
        return
    try:
        _gateway().remove_path(camera.id)
    except GatewayError as exc:
        logger.warning("live playback cleanup skipped for camera %s (%s)", camera.id, exc.reason)
