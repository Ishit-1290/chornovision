"""User persistence helpers."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


def get_by_username(db: Session, username: str) -> User | None:
    """Return the user with ``username`` (exact match), or ``None``."""
    return db.execute(select(User).where(User.username == username)).scalar_one_or_none()


def get_by_id(db: Session, user_id: int) -> User | None:
    """Return the user with ``user_id``, or ``None``."""
    return db.get(User, user_id)


def add(db: Session, user: User) -> User:
    """Persist ``user`` and return it."""
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
