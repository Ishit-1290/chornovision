"""Password hashing (Argon2id) and opaque token helpers.

Passwords are hashed with Argon2id via ``argon2-cffi`` (the default type). Session and
CSRF tokens are high-entropy random values; they are stored only as SHA-256 hashes,
which is appropriate because the tokens are already unguessable and are compared
locally rather than being used as password-equivalent low-entropy inputs.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error

# ``InvalidHashError`` derives from ``ValueError`` rather than ``Argon2Error``, so both
# are caught when verifying or inspecting an untrusted stored hash.
_HASH_ERRORS = (Argon2Error, ValueError, TypeError)

# Argon2id defaults (time_cost=3, memory_cost=64 MiB, parallelism=4) are used.
_hasher = PasswordHasher()

SESSION_TOKEN_BYTES = 32
CSRF_TOKEN_BYTES = 32


def hash_password(password: str) -> str:
    """Return an Argon2id hash for ``password``."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Return ``True`` only if ``password`` matches ``password_hash``."""
    try:
        return _hasher.verify(password_hash, password)
    except _HASH_ERRORS:
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """Return ``True`` if the stored hash should be upgraded to current parameters."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except _HASH_ERRORS:
        return True


def generate_session_token() -> str:
    """Return a new random session token (URL-safe)."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def generate_csrf_token() -> str:
    """Return a new random CSRF token (URL-safe)."""
    return secrets.token_urlsafe(CSRF_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Return the hex SHA-256 digest used to store a token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_equal(a: str, b: str) -> bool:
    """Constant-time comparison of two token digests."""
    return hmac.compare_digest(a, b)
