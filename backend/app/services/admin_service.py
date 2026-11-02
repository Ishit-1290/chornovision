"""Administrator account provisioning.

Used by the ``chronovision-admin create-admin`` command. No default password is ever
hard-coded or logged.
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.config import get_settings
from app.models.user import User
from app.repositories import users as users_repo

_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class AdminError(Exception):
    """Base class for administrator-provisioning errors."""


class InvalidUsernameError(AdminError):
    """The username does not match the allowed pattern."""


class WeakPasswordError(AdminError):
    """The password is shorter than the configured minimum."""


class UserExistsError(AdminError):
    """A user with the given username already exists."""


def create_admin(db: Session, username: str, password: str) -> User:
    """Create the administrator account, or raise :class:`AdminError`."""
    settings = get_settings()
    username = username.strip()
    if not _USERNAME_PATTERN.match(username):
        raise InvalidUsernameError(
            "username must be 1-64 characters using letters, digits, '.', '_' or '-'"
        )
    if len(password) < settings.password_min_length:
        raise WeakPasswordError(
            f"password must be at least {settings.password_min_length} characters"
        )
    if users_repo.get_by_username(db, username) is not None:
        raise UserExistsError(f"user {username!r} already exists")
    user = User(username=username, password_hash=hash_password(password), is_active=True)
    return users_repo.add(db, user)
