"""Live-playback response contract (Phase 10; FR-51, D-62).

The browser receives only what it needs to negotiate a WebRTC session with the gateway:
availability, a coarse state, the opaque gateway path, and the WHEP URL. Camera source
addresses, hostnames, and credentials are never part of this contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

LivePlaybackState = Literal["unavailable", "connecting", "live", "disconnected", "error"]


class LivePlaybackInfo(BaseModel):
    """Read-only live-playback descriptor for one camera."""

    #: True when the gateway is configured/reachable and the camera can be played.
    available: bool
    state: LivePlaybackState
    #: Playback protocol; currently always WebRTC when available.
    protocol: Literal["webrtc"] | None = None
    #: Opaque gateway path (derived from the camera id; contains no source information).
    path: str | None = None
    #: Browser-facing WHEP endpoint. Never contains camera credentials.
    whep_url: str | None = None
    #: Short, non-sensitive explanation for a non-live state.
    detail: str | None = None
