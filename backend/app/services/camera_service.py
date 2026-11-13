"""Camera configuration services.

Handles validation (including stream-address/SSRF checks), uniqueness, and conversion
to API response models that never expose stream credentials.
"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.events.zones import CameraRulesError, validate_camera_configuration
from app.models.camera import Camera, CameraStatus
from app.repositories import cameras as cameras_repo
from app.schemas.camera import CameraRead
from app.services import lifecycle, monitoring_service
from app.services.credential_cipher import encrypt_credentials
from app.services.stream_validation import (
    StreamValidationError,
    redact_stream_reference,
    validate_stream_reference,
)


class CameraError(Exception):
    """Base class for camera configuration errors."""


class CameraNameConflict(CameraError):
    """A camera with the requested name already exists."""


class InvalidStreamReference(CameraError):
    """The stream reference failed validation. ``reason`` is a machine-readable code."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class InvalidCameraConfiguration(CameraError):
    """The camera ``configuration`` (zones / event rules) failed validation."""


def _validate_configuration(configuration: dict[str, object] | None) -> None:
    try:
        validate_camera_configuration(configuration)
    except CameraRulesError as exc:
        raise InvalidCameraConfiguration(str(exc)) from exc


def _validate_stream(reference: str) -> str:
    settings = get_settings()
    try:
        return validate_stream_reference(
            reference,
            allowed_schemes=settings.allowed_stream_schemes,
            allow_private=settings.camera_allow_private_networks,
            resolve=settings.camera_resolve_stream_hostnames,
        )
    except StreamValidationError as exc:
        raise InvalidStreamReference(exc.reason, str(exc)) from exc


def create_camera(
    db: Session,
    *,
    name: str,
    stream_reference: str,
    enabled: bool = True,
    configuration: dict[str, object] | None = None,
    stream_username: str | None = None,
    stream_password: str | None = None,
) -> Camera:
    """Validate and persist a new camera."""
    if cameras_repo.get_by_name(db, name) is not None:
        raise CameraNameConflict(f"a camera named {name!r} already exists")

    _validate_configuration(configuration)

    encrypted_credentials: str | None = None
    if stream_username is not None and stream_password is not None:
        encrypted_credentials = encrypt_credentials(stream_username, stream_password)

    camera = Camera(
        name=name,
        stream_reference=_validate_stream(stream_reference),
        enabled=enabled,
        status=CameraStatus.CONFIGURED.value,
        configuration=dict(configuration or {}),
        stream_credentials_encrypted=encrypted_credentials,
    )
    try:
        return cameras_repo.add(db, camera)
    except IntegrityError as exc:  # pragma: no cover - guarded by the check above
        db.rollback()
        raise CameraNameConflict(f"a camera named {name!r} already exists") from exc


def update_camera(
    db: Session,
    camera: Camera,
    *,
    name: str | None = None,
    stream_reference: str | None = None,
    enabled: bool | None = None,
    configuration: dict[str, object] | None = None,
    stream_username: str | None = None,
    stream_password: str | None = None,
    clear_stream_credentials: bool = False,
) -> Camera:
    """Apply the provided changes to ``camera`` and persist them."""
    if name is not None and name != camera.name:
        existing = cameras_repo.get_by_name(db, name)
        if existing is not None and existing.id != camera.id:
            raise CameraNameConflict(f"a camera named {name!r} already exists")
        camera.name = name

    if stream_reference is not None:
        camera.stream_reference = _validate_stream(stream_reference)

    if clear_stream_credentials:
        camera.stream_credentials_encrypted = None
    elif stream_username is not None and stream_password is not None:
        camera.stream_credentials_encrypted = encrypt_credentials(stream_username, stream_password)

    if enabled is not None:
        camera.enabled = enabled
        if not enabled and lifecycle.coerce_status(camera.status) in lifecycle.PROCESSING_STATES:
            # Disabling a camera stops its runtime; the configuration is retained.
            camera.status = lifecycle.transition(camera.status, CameraStatus.STOPPED).value

    if configuration is not None:
        _validate_configuration(configuration)
        camera.configuration = dict(configuration)

    try:
        return cameras_repo.save(db, camera)
    except IntegrityError as exc:  # pragma: no cover - guarded by the check above
        db.rollback()
        raise CameraNameConflict(f"a camera named {name!r} already exists") from exc


def to_read(camera: Camera) -> CameraRead:
    """Convert ``camera`` to a response model with a redacted stream reference.

    The lifecycle ``status`` is the *effective* state: a persisted processing state whose
    worker has gone silent is projected as ``disconnected`` (see
    :func:`app.services.monitoring_service.effective_status`). This keeps ``GET /api/cameras``
    consistent with ``GET /api/monitoring/status`` instead of reporting a stale ``connecting``.
    """
    return CameraRead(
        id=camera.id,
        name=camera.name,
        stream_reference=redact_stream_reference(camera.stream_reference),
        enabled=camera.enabled,
        status=monitoring_service.effective_status(camera),
        configuration=dict(camera.configuration or {}),
        has_stream_credentials=bool(camera.stream_credentials_encrypted),
        created_at=camera.created_at,
        updated_at=camera.updated_at,
    )
