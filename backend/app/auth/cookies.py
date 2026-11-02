"""Cookie helpers for the session and CSRF tokens.

The session cookie is HttpOnly; the CSRF cookie is intentionally readable by the
browser so a same-origin client can echo it in the ``X-CSRF-Token`` header.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import Response

from app.config import get_settings
from app.utils import ensure_utc, utcnow


def _seconds_until(expires_at: datetime) -> int:
    return max(0, int((ensure_utc(expires_at) - utcnow()).total_seconds()))


def set_session_cookie(response: Response, token: str, expires_at: datetime) -> None:
    """Set the HttpOnly session cookie."""
    settings = get_settings()
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=_seconds_until(expires_at),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite.value,
        path="/",
    )


def set_csrf_cookie(response: Response, token: str) -> None:
    """Set the CSRF cookie (readable by the browser)."""
    settings = get_settings()
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=False,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite.value,
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    """Delete the session and CSRF cookies (logout)."""
    settings = get_settings()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
