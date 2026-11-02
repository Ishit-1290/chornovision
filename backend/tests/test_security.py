"""Tests for security primitives (password hashing and token helpers)."""

from __future__ import annotations

from app.auth.security import (
    generate_csrf_token,
    generate_session_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    tokens_equal,
    verify_password,
)


def test_hash_password_uses_argon2id() -> None:
    digest = hash_password("correct-horse-battery-staple")
    assert digest.startswith("$argon2id$")


def test_verify_password_roundtrip() -> None:
    digest = hash_password("correct-horse-battery-staple")
    assert verify_password(digest, "correct-horse-battery-staple") is True
    assert verify_password(digest, "wrong-password") is False


def test_verify_password_handles_invalid_hash() -> None:
    assert verify_password("not-a-valid-hash", "whatever") is False


def test_password_needs_rehash_handles_invalid_hash() -> None:
    assert password_needs_rehash("not-a-valid-hash") is True
    assert password_needs_rehash(hash_password("correct-horse-battery-staple")) is False


def test_hash_password_is_salted() -> None:
    assert hash_password("same-password") != hash_password("same-password")


def test_hash_token_is_deterministic_and_not_reversible() -> None:
    token = "a-secret-token"
    digest = hash_token(token)
    assert digest == hash_token(token)
    assert len(digest) == 64
    assert token not in digest


def test_tokens_equal() -> None:
    assert tokens_equal("abc", "abc") is True
    assert tokens_equal("abc", "abd") is False


def test_generated_tokens_are_unique_and_long() -> None:
    tokens = {generate_session_token() for _ in range(50)}
    assert len(tokens) == 50
    assert all(len(token) >= 32 for token in tokens)
    assert generate_csrf_token() != generate_csrf_token()
