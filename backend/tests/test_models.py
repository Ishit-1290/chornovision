"""Tests for the ORM models and schema registration."""

from __future__ import annotations

from app.models import Base


def test_expected_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "sessions",
        "audit_logs",
        "cameras",
        "events",
        "event_transitions",
        "evidence",
    }


def test_users_columns_match_contract() -> None:
    columns = set(Base.metadata.tables["users"].columns.keys())
    assert columns == {
        "id",
        "username",
        "password_hash",
        "is_active",
        "created_at",
        "updated_at",
    }


def test_sessions_columns_match_contract() -> None:
    columns = set(Base.metadata.tables["sessions"].columns.keys())
    assert columns == {
        "id",
        "user_id",
        "session_token_hash",
        "csrf_token_hash",
        "created_at",
        "expires_at",
        "revoked_at",
    }


def test_audit_logs_columns_match_contract() -> None:
    columns = set(Base.metadata.tables["audit_logs"].columns.keys())
    # The Python attribute is ``log_metadata``; the column keeps the documented name.
    assert columns == {
        "id",
        "user_id",
        "action",
        "resource_type",
        "resource_id",
        "created_at",
        "metadata",
    }


def test_username_is_unique() -> None:
    username = Base.metadata.tables["users"].columns["username"]
    assert username.unique is True


def test_cameras_columns_match_contract() -> None:
    columns = set(Base.metadata.tables["cameras"].columns.keys())
    assert columns == {
        "id",
        "name",
        "stream_reference",
        # Fernet-encrypted credential pair (Phase 10; D-64); nullable, never a response field.
        "stream_credentials_encrypted",
        "enabled",
        "status",
        "configuration",
        "created_at",
        "updated_at",
    }


def test_camera_name_is_unique() -> None:
    name = Base.metadata.tables["cameras"].columns["name"]
    assert name.unique is True


def test_camera_required_columns_are_not_nullable() -> None:
    table = Base.metadata.tables["cameras"]
    for column in ("name", "stream_reference", "enabled", "status", "configuration"):
        assert table.columns[column].nullable is False
