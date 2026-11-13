"""Typed, validated application configuration for ChronoVision.

Loads configuration from environment variables and optional ``.env`` files, validates it,
and fails fast when required values are missing or insecure. This module only defines the
settings; connecting to PostgreSQL, defining routes, and authentication live in their own
modules.

Precedence (highest first): constructor arguments, process environment variables,
``<repo>/.env`` then ``backend/.env`` (later files take precedence), defaults.

Secrets are held as :class:`pydantic.SecretStr` so they are not printed in logs or
tracebacks. Placeholder values (for example the entries in ``.env.example``) are
rejected on purpose, so copying the example file cannot silently yield an insecure
deployment.
"""

from __future__ import annotations

import re
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus, urlsplit

from pydantic import Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

# Candidate .env files, resolved relative to the repository (not the current working
# directory). Missing files are ignored. Later files take precedence.
ENV_FILES = (REPO_ROOT / ".env", BACKEND_DIR / ".env")

MIN_SECRET_LENGTH = 32

# Substrings that indicate an insecure placeholder secret rather than a real value.
_PLACEHOLDER_MARKERS = (
    "change_me",
    "changeme",
    "replace_me",
    "your_secret",
    "placeholder",
    "example",
)


class Environment(StrEnum):
    """Deployment environment."""

    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class LogLevel(StrEnum):
    """Allowed application log levels."""

    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    DEBUG = "DEBUG"


class SameSite(StrEnum):
    """Allowed ``SameSite`` values for authentication cookies."""

    LAX = "lax"
    STRICT = "strict"
    NONE = "none"


def _validate_secret(value: str, field_name: str) -> str:
    """Reject short or placeholder secrets. Returns the validated raw value."""
    if len(value) < MIN_SECRET_LENGTH:
        raise ValueError(f"{field_name} must be at least {MIN_SECRET_LENGTH} characters long")
    lowered = value.lower()
    for marker in _PLACEHOLDER_MARKERS:
        if marker in lowered:
            raise ValueError(
                f"{field_name} still contains the placeholder text {marker!r}; set a real value"
            )
    return value


class Settings(BaseSettings):
    """Application settings loaded from the environment.

    Field names map to upper-case environment variables, e.g. ``secret_key`` ->
    ``SECRET_KEY``, ``postgres_password`` -> ``POSTGRES_PASSWORD``.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILES,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Application ------------------------------------------------------------
    app_name: str = "ChronoVision"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    log_level: LogLevel = LogLevel.INFO

    # -- PostgreSQL -------------------------------------------------------------
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "chronovision"
    postgres_user: str = "chronovision"
    postgres_password: SecretStr

    # -- Security ---------------------------------------------------------------
    secret_key: SecretStr
    session_cookie_name: str = "chronovision_session"
    session_ttl_seconds: int = Field(default=86_400, gt=0)
    internal_api_token: SecretStr

    # -- Session cookies / login protection -------------------------------------
    session_cookie_secure: bool = False
    session_cookie_samesite: SameSite = SameSite.LAX
    csrf_cookie_name: str = "chronovision_csrf"
    login_rate_limit_attempts: int = Field(default=5, ge=1)
    login_rate_limit_window_seconds: int = Field(default=300, ge=1)

    # -- Password policy --------------------------------------------------------
    password_min_length: int = Field(default=12, ge=8)

    # -- Cameras / stream-address policy (Phase 3; SEC-06) -----------------------
    # Comma-separated list of URL schemes accepted for camera stream references.
    camera_allowed_stream_schemes: str = "rtsp,rtsps"
    # Cameras normally live on the local network, so RFC1918/ULA ranges are allowed
    # by default. Loopback, link-local (incl. cloud metadata), multicast, reserved,
    # and unspecified addresses are always rejected (see app/services/stream_validation).
    camera_allow_private_networks: bool = True
    # Resolving hostnames at configuration time is subject to DNS rebinding, so it is
    # off by default; the connection-time enforcement belongs to the Phase 4 worker.
    camera_resolve_stream_hostnames: bool = False
    # A camera in a processing state whose worker has not reported/heartbeated within this
    # window is reported as ``disconnected`` (read-time projection; D-24, Phase 4).
    worker_heartbeat_timeout_seconds: int = Field(default=15, ge=1)

    # -- Live playback / MediaMTX gateway (Phase 10; D-62/D-65) ------------------
    # Playback is opt-in: deploying MediaMTX alone never enables the dashboard player.
    # When enabled, both URLs below are required and validated at startup.
    live_playback_enabled: bool = False
    # Backend -> gateway management API (a trusted internal service; loopback or the
    # compose service name is expected). Never exposed to the browser.
    mediamtx_api_url: str = ""
    # Browser-facing WebRTC base URL (e.g. https://media.example.lan:8889). The WHEP URL
    # returned to the dashboard is ``<this>/<path>/whep``; no camera source is exposed.
    mediamtx_webrtc_url: str = ""
    # Optional HTTP Basic credentials for the gateway management API.
    mediamtx_api_username: str = ""
    mediamtx_api_password: SecretStr = SecretStr("")
    # Generated gateway path names are ``<prefix>-cam-<camera_id>`` (stable + safe).
    mediamtx_path_prefix: str = "cv"
    mediamtx_request_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    # Pin the validated camera IP literal in the gateway source URL so the gateway cannot
    # re-resolve a rebinding hostname. Disable only for TLS/SNI-vhosted cameras (documented
    # residual, mirroring VISION_STREAM_HOST_MODE=hostname; D-28/D-65).
    live_gateway_pin_hosts: bool = True
    # Ask the gateway to close its camera connection this many seconds after the last
    # viewer leaves (0 = keep the source connection open).
    live_gateway_close_after_seconds: int = Field(default=10, ge=0)

    # -- Evidence (bounded + configurable; defaults per DECISIONS.md D-11/D-43).
    # These are the single source of truth for both the backend (retention, authorized
    # access) and the vision worker (capture policy), so the two processes never diverge.
    evidence_enabled: bool = True
    evidence_dir: Path = REPO_ROOT / "data" / "evidence"
    # Rolling pre-event buffer window per camera (decimated at the process frame rate).
    evidence_rolling_buffer_seconds: int = Field(default=15, ge=1)
    evidence_pre_event_seconds: int = Field(default=5, ge=0)
    evidence_post_event_seconds: int = Field(default=5, ge=0)
    #: Snapshot on every event trigger (W §9 step 3). Clip capture follows automatically.
    evidence_snapshot_enabled: bool = True
    evidence_clip_fps: float = Field(default=5.0, gt=0.0, le=60.0)
    #: Upper bound on frames retained for a single clip (memory guard for the encoder).
    evidence_clip_max_frames: int = Field(default=150, ge=1)
    evidence_retention_days: int = Field(default=30, ge=1)
    evidence_storage_limit_gb: int = Field(default=25, ge=1)
    #: Run retention opportunistically when evidence metadata is registered. **Off by
    #: default** so deletion is never a side effect of capture: retention is an explicit,
    #: auditable operation via ``chronovision-admin prune-evidence`` (or a scheduled job).
    evidence_retention_on_register: bool = False

    @field_validator("postgres_password", "secret_key", "internal_api_token")
    @classmethod
    def _check_secret(cls, value: SecretStr, info: ValidationInfo) -> SecretStr:
        return SecretStr(_validate_secret(value.get_secret_value(), info.field_name))

    @field_validator("camera_allowed_stream_schemes")
    @classmethod
    def _check_stream_schemes(cls, value: str) -> str:
        schemes = [scheme.strip().lower() for scheme in value.split(",") if scheme.strip()]
        if not schemes:
            raise ValueError("camera_allowed_stream_schemes must list at least one scheme")
        for scheme in schemes:
            if not re.fullmatch(r"[a-z][a-z0-9+.\-]*", scheme):
                raise ValueError(f"invalid URL scheme {scheme!r} in camera_allowed_stream_schemes")
        return ",".join(schemes)

    @field_validator("mediamtx_path_prefix")
    @classmethod
    def _check_path_prefix(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,31}", value):
            raise ValueError(
                "mediamtx_path_prefix must be 1-32 characters of [A-Za-z0-9_-] "
                "and start with a letter or digit"
            )
        return value

    @model_validator(mode="after")
    def _check_environment(self) -> Settings:
        if self.environment is Environment.PRODUCTION and self.debug:
            raise ValueError("debug must be False when environment is 'production'")
        if self.session_cookie_samesite is SameSite.NONE and not self.session_cookie_secure:
            raise ValueError(
                "session_cookie_secure must be True when session_cookie_samesite is 'none'"
            )
        self._check_live_playback()
        return self

    def _check_live_playback(self) -> None:
        """Validate the opt-in live-playback gateway settings (D-62/D-65)."""
        configured = bool(self.mediamtx_api_url or self.mediamtx_webrtc_url)
        if not self.live_playback_enabled and not configured:
            return
        if not self.live_playback_enabled:
            # URLs without the explicit enable flag are a configuration mistake, not a
            # silent activation: deploying the gateway must never enable playback by itself.
            raise ValueError(
                "MEDIAMTX_API_URL/MEDIAMTX_WEBRTC_URL are set but LIVE_PLAYBACK_ENABLED is "
                "false; set LIVE_PLAYBACK_ENABLED=true to activate live playback"
            )
        for field_name, raw in (
            ("MEDIAMTX_API_URL", self.mediamtx_api_url),
            ("MEDIAMTX_WEBRTC_URL", self.mediamtx_webrtc_url),
        ):
            if not raw:
                raise ValueError(f"{field_name} is required when LIVE_PLAYBACK_ENABLED is true")
            parts = urlsplit(raw)
            if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
                raise ValueError(f"{field_name} must be an absolute http(s) URL")
            if parts.username or parts.password:
                raise ValueError(f"{field_name} must not embed credentials")
            if parts.query or parts.fragment:
                raise ValueError(f"{field_name} must not include a query string or fragment")

    @property
    def is_production(self) -> bool:
        """True when running in the production environment."""
        return self.environment is Environment.PRODUCTION

    @property
    def allowed_stream_schemes(self) -> frozenset[str]:
        """The set of URL schemes accepted for camera stream references."""
        return frozenset(self.camera_allowed_stream_schemes.split(","))

    @property
    def database_url(self) -> str:
        """SQLAlchemy database URL built from the configured PostgreSQL parts.

        The password is URL-encoded. The ``psycopg`` driver is declared in Phase 2;
        this property only constructs the connection string.
        """
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password.get_secret_value())
        return (
            f"postgresql+psycopg://{user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached, validated application settings.

    Fails fast with a :class:`pydantic.ValidationError` when required configuration
    is missing or invalid.
    """
    return Settings()


def clear_settings_cache() -> None:
    """Clear the cached settings (used by tests and by config reloads)."""
    get_settings.cache_clear()
