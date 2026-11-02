"""FastAPI authentication dependencies and CSRF enforcement."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.rate_limit import LoginRateLimiter
from app.auth.security import hash_token, tokens_equal
from app.config import get_settings
from app.db import get_db
from app.models.auth_session import UserSession
from app.models.user import User
from app.repositories import sessions as sessions_repo
from app.utils import ensure_utc, utcnow

CSRF_HEADER_NAME = "X-CSRF-Token"


@dataclass
class AuthContext:
    """The authenticated user and the session used for the current request."""

    user: User
    session: UserSession


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


def resolve_session(db: Session, raw_token: str | None) -> AuthContext | None:
    """Resolve a raw session token to an :class:`AuthContext`, or ``None``.

    Shared by the HTTP dependency and the WebSocket handshake so both surfaces enforce
    exactly the same session rules: unknown, revoked, expired, inactive-user, and
    inactive-account sessions are all rejected.
    """
    if not raw_token:
        return None

    session = sessions_repo.get_by_token_hash(db, hash_token(raw_token))
    if session is None or session.revoked_at is not None:
        return None
    if ensure_utc(session.expires_at) <= utcnow():
        return None

    user = session.user
    if user is None or not user.is_active:
        return None

    return AuthContext(user=user, session=session)


def get_auth_context(request: Request, db: Session = Depends(get_db)) -> AuthContext:
    """Resolve and validate the current session from the session cookie.

    Rejects missing, unknown, revoked, expired, inactive-user, and inactive-account
    sessions.
    """
    settings = get_settings()
    auth = resolve_session(db, request.cookies.get(settings.session_cookie_name))
    if auth is None:
        raise _unauthorized()
    return auth


def get_current_user(auth: AuthContext = Depends(get_auth_context)) -> User:
    """Return the authenticated user."""
    return auth.user


def enforce_csrf(request: Request, session: UserSession) -> None:
    """Require a valid ``X-CSRF-Token`` header bound to ``session``."""
    presented = request.headers.get(CSRF_HEADER_NAME)
    if not presented or not tokens_equal(hash_token(presented), session.csrf_token_hash):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing CSRF token",
        )


def get_csrf_auth_context(
    request: Request, auth: AuthContext = Depends(get_auth_context)
) -> AuthContext:
    """Require an authenticated session *and* a valid CSRF token.

    Use this for state-changing, cookie-authenticated endpoints (W §5).
    """
    enforce_csrf(request, auth.session)
    return auth


_login_limiter: LoginRateLimiter | None = None
_login_limiter_lock = threading.Lock()


def get_login_limiter() -> LoginRateLimiter:
    """Return the process-wide login rate limiter (created on first use)."""
    global _login_limiter
    if _login_limiter is None:
        with _login_limiter_lock:
            if _login_limiter is None:
                settings = get_settings()
                _login_limiter = LoginRateLimiter(
                    max_attempts=settings.login_rate_limit_attempts,
                    window_seconds=settings.login_rate_limit_window_seconds,
                )
    return _login_limiter


def reset_login_limiter() -> None:
    """Drop the cached limiter (used by tests)."""
    global _login_limiter
    _login_limiter = None
