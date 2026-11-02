"""Authentication request/response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.user import UserRead


class LoginRequest(BaseModel):
    """Credentials submitted to ``POST /api/auth/login``."""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class LoginResponse(BaseModel):
    """Result of a successful login. The CSRF token is delivered via cookie."""

    user: UserRead
    expires_at: datetime


class MessageResponse(BaseModel):
    """Simple acknowledgement payload."""

    detail: str
