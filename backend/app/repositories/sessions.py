"""Authentication-session persistence helpers."""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.auth_session import UserSession
from app.utils import utcnow


def get_by_token_hash(db: Session, token_hash: str) -> UserSession | None:
    """Return the session matching the (hashed) token, or ``None``."""
    return db.execute(
        select(UserSession).where(UserSession.session_token_hash == token_hash)
    ).scalar_one_or_none()


def add(db: Session, session: UserSession) -> UserSession:
    """Persist a new session and return it."""
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def revoke(db: Session, session: UserSession) -> None:
    """Mark a single session as revoked."""
    session.revoked_at = utcnow()
    db.commit()


def revoke_all_for_user(db: Session, user_id: int) -> int:
    """Revoke every active session for a user; returns the number affected."""
    result = db.execute(
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    db.commit()
    return int(result.rowcount or 0)
