"""Vision-worker configuration (Phase 4).

Worker-specific knobs are read from ``VISION_*`` environment variables (and the same
``.env`` files the backend uses). Security-relevant values that must stay identical
between the backend and the worker — the internal API token and the stream-address
policy — are read from :mod:`app.config` so there is a single source of truth (no
duplicated secrets or diverging SSRF policy).

All thresholds are explicit configuration (G §15.2); nothing about sampling, buffering,
detection, or timeouts is hard-coded in the pipeline modules.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from app.config import ENV_FILES, get_settings
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class StreamHostMode(StrEnum):
    """How a hostname stream reference is turned into a connectable URL.

    - ``PIN`` (default): the resolved, validated IP literal replaces the hostname in the
      URL handed to the decoder, so OpenCV/FFmpeg cannot re-resolve and cannot be
      rebound (enforceable destination pinning).
    - ``HOSTNAME``: keep the original hostname (documented residual risk: the decoder
      re-resolves independently, so DNS-rebinding protection is not enforceable). Only
      for cameras that require a virtual host and cannot be addressed by IP.
    """

    PIN = "pin"
    HOSTNAME = "hostname"


class TrackerKind(StrEnum):
    """Selectable per-camera tracker."""

    BYTETRACK = "bytetrack"
    IOU = "iou"


class VisionSettings(BaseSettings):
    """Validated worker settings (``VISION_*`` environment variables)."""

    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        env_prefix="VISION_",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Process ----------------------------------------------------------------
    log_level: str = "INFO"
    # Phase 4 processes a single camera (CON-08); multi-camera is Phase 8.
    max_concurrent_cameras: int = Field(default=1, ge=1)

    # -- Backend internal API ---------------------------------------------------
    backend_base_url: str = "http://127.0.0.1:8000"
    internal_request_timeout_seconds: float = Field(default=5.0, gt=0)
    internal_max_retries: int = Field(default=3, ge=0)

    # -- Supervisor loop --------------------------------------------------------
    poll_interval_seconds: float = Field(default=2.0, gt=0)
    heartbeat_interval_seconds: float = Field(default=5.0, gt=0)

    # -- Connection / reconnect -------------------------------------------------
    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    read_timeout_seconds: float = Field(default=10.0, gt=0)
    reconnect_initial_backoff_seconds: float = Field(default=1.0, ge=0)
    reconnect_max_backoff_seconds: float = Field(default=30.0, ge=0)
    # 0 means "retry indefinitely" with capped backoff (continuous operation).
    reconnect_max_attempts: int = Field(default=0, ge=0)

    # -- Ingestion / sampling ---------------------------------------------------
    queue_maxsize: int = Field(default=8, ge=1)
    process_target_fps: float = Field(default=5.0, gt=0)
    # 0 disables resizing; otherwise frames are scaled so width == process_width.
    process_width: int = Field(default=0, ge=0)

    # -- Detection (lazy model loading) ----------------------------------------
    detector_weights: str = "yolo11n.pt"
    detector_device: str = "cpu"
    detector_confidence: float = Field(default=0.25, gt=0, le=1)
    detector_iou: float = Field(default=0.7, gt=0, le=1)
    detector_imgsz: int = Field(default=640, ge=64)
    # Restrict to the COCO "person" class by default (Phase 4 vertical slice).
    detector_person_only: bool = True

    # -- Tracking ---------------------------------------------------------------
    tracker: TrackerKind = TrackerKind.BYTETRACK

    # -- Backpressure / degraded signalling -------------------------------------
    # A window of N processed frames over which the dropped-frame ratio is evaluated.
    degraded_window_frames: int = Field(default=50, ge=1)
    degraded_drop_ratio: float = Field(default=0.5, ge=0.0, le=1.0)

    # -- Observability ----------------------------------------------------------
    # Bounded ring of recent frame-processing latencies kept per camera for p50/p95/p99
    # reporting. 0 (default) disables sampling; benchmarking enables it.
    metrics_latency_sample_capacity: int = Field(default=0, ge=0)

    # -- Streaming --------------------------------------------------------------
    stream_host_mode: StreamHostMode = StreamHostMode.PIN
    # Rolling pre-event buffer (FR-35); bounded by both count and bytes. When unset, the
    # count is derived from ``EVIDENCE_ROLLING_BUFFER_SECONDS`` × the process frame rate so
    # the configured evidence window is actually retained (the byte cap still applies).
    rolling_buffer_frames: int | None = Field(default=None, ge=1)
    rolling_buffer_max_mb: int = Field(default=256, ge=1)

    # -- Evidence capture / event handoff (Phase 6) ------------------------------
    # All queues/spools are bounded; overflow records an explicit failure or drops only at
    # the configured hard limit (never silently).
    evidence_encoder_queue_maxsize: int = Field(default=16, ge=1)
    evidence_handoff_queue_maxsize: int = Field(default=1000, ge=1)
    evidence_handoff_spool_max_mb: int = Field(default=5, ge=1)
    evidence_handoff_max_attempts: int = Field(default=5, ge=1)
    evidence_handoff_retry_backoff_seconds: float = Field(default=0.5, ge=0)

    @property
    def allowed_stream_schemes(self) -> frozenset[str]:
        """Reuse the backend's configured camera stream scheme allow-list."""
        return get_settings().allowed_stream_schemes

    @property
    def allow_private_networks(self) -> bool:
        """Reuse the backend's configured private-network policy."""
        return get_settings().camera_allow_private_networks

    @property
    def internal_api_token(self) -> str:
        """The shared internal token (single source of truth: ``app.config``)."""
        return get_settings().internal_api_token.get_secret_value()


@lru_cache(maxsize=1)
def get_vision_settings() -> VisionSettings:
    """Return the cached, validated vision-worker settings."""
    return VisionSettings()


def clear_vision_settings_cache() -> None:
    """Clear the cached settings (used by tests)."""
    get_vision_settings.cache_clear()
