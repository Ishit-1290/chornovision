"""Camera request/response schemas.

Response schemas expose a **redacted** stream reference (no userinfo, query, or
fragment) so that credentials or signed tokens can never leak through the API.

Phase 10 adds an explicit, write-only credential pair (``stream_username`` /
``stream_password``). It is encrypted at rest (D-64) and the response only reveals
``has_stream_credentials`` so the dashboard can show whether authentication is configured
without ever receiving the secret.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _CredentialFields(BaseModel):
    """Shared, write-only credential fields and their pairing rules."""

    stream_username: str | None = Field(default=None, min_length=1, max_length=256)
    stream_password: str | None = Field(default=None, min_length=1, max_length=512)

    @model_validator(mode="after")
    def _check_credentials(self) -> _CredentialFields:
        if (self.stream_username is None) != (self.stream_password is None):
            raise ValueError("stream_username and stream_password must be provided together")
        return self


class CameraCreate(_CredentialFields):
    """Body of ``POST /api/cameras``."""

    name: str = Field(min_length=1, max_length=128)
    stream_reference: str = Field(min_length=1, max_length=2048)
    enabled: bool = True
    configuration: dict[str, object] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped


class CameraUpdate(_CredentialFields):
    """Body of ``PATCH /api/cameras/{id}``. Omitted fields are left unchanged.

    Credentials are left unchanged when both fields are omitted. ``clear_stream_credentials``
    removes a previously stored pair; it cannot be combined with a new pair.
    """

    name: str | None = Field(default=None, min_length=1, max_length=128)
    stream_reference: str | None = Field(default=None, min_length=1, max_length=2048)
    enabled: bool | None = None
    configuration: dict[str, object] | None = None
    clear_stream_credentials: bool = False

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("name must not be blank")
        return stripped

    @model_validator(mode="after")
    def _check_clear(self) -> CameraUpdate:
        if self.clear_stream_credentials and self.stream_username is not None:
            raise ValueError(
                "clear_stream_credentials cannot be combined with new stream credentials"
            )
        return self


class CameraRead(BaseModel):
    """Public representation of a camera. Never contains stream credentials."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    stream_reference: str
    enabled: bool
    status: str
    configuration: dict[str, object]
    #: True when an encrypted credential pair is stored (the pair itself is never exposed).
    has_stream_credentials: bool = False
    created_at: datetime
    updated_at: datetime
