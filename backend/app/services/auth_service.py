"""Authentication and session lifecycle logic.

The raw session token and CSRF token exist only in the login response cookies; the
database stores only their SHA-256 hashes.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from functools import lru_cache

from sqlalchemy.orm import Session

from app.auth.security import (
    generate_csrf_token,
    generate_session_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.config import get_settings
from app.models.auth_session import UserSession
from app.models.user import User
from app.repositories import sessions as sessions_repo
from app.repositories import users as users_repo
from app.utils import utcnow


@lru_cache(maxsize=1)
def _dummy_password_hash() -> str:
    """A throwaway hash used to equalise timing for unknown usernames."""
    return hash_password(secrets.token_urlsafe(24))


def authenticate(db: Session, username: str, password: str) -> User | None:
    """Return the authenticated active user, or ``None``.

    Verification always performs an Argon2id check so that the response time does not
    reveal whether the username exists.
    """
    user = users_repo.get_by_username(db, username)
    if user is None:
        verify_password(_dummy_password_hash(), password)
        return None
    if not verify_password(user.password_hash, password):
        return None
    if not user.is_active:
        return None
    return user


def create_session(db: Session, user: User) -> tuple[str, str, UserSession]:
    """Create a server-side session.

    Returns ``(raw_session_token, raw_csrf_token, session)``. Only hashes are stored.
    """
    settings = get_settings()
    raw_token = generate_session_token()
    csrf_token = generate_csrf_token()
    session = UserSession(
        user_id=user.id,
        session_token_hash=hash_token(raw_token),
        csrf_token_hash=hash_token(csrf_token),
        expires_at=utcnow() + timedelta(seconds=settings.session_ttl_seconds),
    )
    return raw_token, csrf_token, sessions_repo.add(db, session)


def revoke_session(db: Session, session: UserSession) -> None:
    """Revoke a single session (logout)."""
    sessions_repo.revoke(db, session)
