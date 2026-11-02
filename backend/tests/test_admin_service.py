"""Tests for administrator provisioning and the admin CLI."""

from __future__ import annotations

import io
import sys

import pytest
from sqlalchemy.orm import Session

from app import cli
from app.auth.security import verify_password
from app.config import get_settings
from app.models import User
from app.services.admin_service import (
    InvalidUsernameError,
    UserExistsError,
    WeakPasswordError,
    create_admin,
)

STRONG_PASSWORD = "correct-horse-battery-staple"


def test_create_admin_hashes_password(db_session_factory, admin_env) -> None:
    db: Session = db_session_factory()
    try:
        user = create_admin(db, "admin", STRONG_PASSWORD)
        assert user.id is not None
        assert user.password_hash != STRONG_PASSWORD
        assert STRONG_PASSWORD not in user.password_hash
        assert verify_password(user.password_hash, STRONG_PASSWORD) is True
        assert user.is_active is True
    finally:
        db.close()


def test_create_admin_rejects_duplicate(db_session_factory, admin_env) -> None:
    db: Session = db_session_factory()
    try:
        create_admin(db, "admin", STRONG_PASSWORD)
        with pytest.raises(UserExistsError):
            create_admin(db, "admin", STRONG_PASSWORD)
    finally:
        db.close()


@pytest.mark.parametrize("username", ["", "  ", "has space", "bad/slash", "a" * 65])
def test_create_admin_rejects_invalid_username(db_session_factory, admin_env, username) -> None:
    db: Session = db_session_factory()
    try:
        with pytest.raises(InvalidUsernameError):
            create_admin(db, username, STRONG_PASSWORD)
    finally:
        db.close()


def test_create_admin_rejects_weak_password(db_session_factory, admin_env) -> None:
    db: Session = db_session_factory()
    try:
        with pytest.raises(WeakPasswordError):
            create_admin(db, "admin", "short")
    finally:
        db.close()


def test_password_minimum_comes_from_settings(admin_env) -> None:
    expected = get_settings().password_min_length
    assert expected >= 12


def test_cli_create_admin_succeeds(db_session_factory, admin_env, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "get_session_factory", lambda: db_session_factory)
    monkeypatch.setattr(cli, "dispose_engine", lambda: None)
    monkeypatch.setattr(sys, "stdin", io.StringIO(STRONG_PASSWORD + "\n"))

    assert cli.main(["create-admin", "--username", "admin", "--password-stdin"]) == 0
    out = capsys.readouterr().out
    assert "admin" in out
    assert STRONG_PASSWORD not in out

    db: Session = db_session_factory()
    try:
        user = db.query(User).filter_by(username="admin").one()
        assert verify_password(user.password_hash, STRONG_PASSWORD) is True
    finally:
        db.close()


def test_cli_duplicate_user_exits_nonzero(
    db_session_factory, admin_env, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli, "get_session_factory", lambda: db_session_factory)
    monkeypatch.setattr(cli, "dispose_engine", lambda: None)
    monkeypatch.setattr(sys, "stdin", io.StringIO(STRONG_PASSWORD + "\n"))

    assert cli.main(["create-admin", "--username", "admin", "--password-stdin"]) == 0
    monkeypatch.setattr(sys, "stdin", io.StringIO(STRONG_PASSWORD + "\n"))
    assert cli.main(["create-admin", "--username", "admin", "--password-stdin"]) == 1


def test_cli_weak_password_exits_nonzero(db_session_factory, admin_env, monkeypatch) -> None:
    monkeypatch.setattr(cli, "get_session_factory", lambda: db_session_factory)
    monkeypatch.setattr(cli, "dispose_engine", lambda: None)
    monkeypatch.setattr(sys, "stdin", io.StringIO("short\n"))
    assert cli.main(["create-admin", "--username", "admin", "--password-stdin"]) == 1
