"""Tests for the Phase 1 configuration module (backend/app/config.py)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import (
    MIN_SECRET_LENGTH,
    Environment,
    LogLevel,
    Settings,
    clear_settings_cache,
    get_settings,
)

# A minimal set of valid required values (>= MIN_SECRET_LENGTH, non-placeholder).
REQUIRED = {
    "postgres_password": "pg" * 20,
    "secret_key": "sk" * 20,
    "internal_api_token": "tok" * 20,
}


def make_settings(**overrides: object) -> Settings:
    """Build Settings from valid values plus overrides, ignoring any .env file."""
    data: dict[str, object] = {**REQUIRED, **overrides}
    return Settings(_env_file=None, **data)


def test_valid_settings_build() -> None:
    settings = make_settings()
    assert settings.app_name == "ChronoVision"
    assert settings.environment is Environment.DEVELOPMENT
    assert settings.debug is False
    assert settings.log_level is LogLevel.INFO
    assert settings.is_production is False


def test_defaults_are_applied() -> None:
    settings = make_settings()
    assert settings.postgres_host == "localhost"
    assert settings.postgres_port == 5432
    assert settings.postgres_db == "chronovision"
    assert settings.session_cookie_name == "chronovision_session"
    assert settings.session_ttl_seconds == 86_400
    assert settings.evidence_pre_event_seconds == 5
    assert settings.evidence_post_event_seconds == 5
    assert settings.evidence_retention_days == 30
    assert settings.evidence_storage_limit_gb == 25


def test_database_url_is_computed_and_encoded() -> None:
    settings = make_settings(
        postgres_user="chrono",
        postgres_host="db",
        postgres_port=6000,
        postgres_db="chronovision",
        postgres_password="p@ss:word/" + "x" * 30,
    )
    url = settings.database_url
    assert url.startswith("postgresql+psycopg://chrono:")
    assert "p%40ss%3Aword%2F" in url
    assert url.endswith("@db:6000/chronovision")


def test_secrets_are_masked() -> None:
    settings = make_settings()
    assert settings.secret_key.get_secret_value() == "sk" * 20
    assert "sk" * 20 not in repr(settings.secret_key)
    assert "pg" * 20 not in repr(settings.postgres_password)
    assert "tok" * 20 not in repr(settings.internal_api_token)


def test_missing_required_secret_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, secret_key="sk" * 20, internal_api_token="tok" * 20)


def test_short_secret_is_rejected() -> None:
    with pytest.raises(ValidationError) as excinfo:
        make_settings(secret_key="short")
    assert "secret_key" in str(excinfo.value)


def test_placeholder_secret_is_rejected() -> None:
    placeholder = "CHANGE_ME_" + "a" * (MIN_SECRET_LENGTH)
    with pytest.raises(ValidationError) as excinfo:
        make_settings(internal_api_token=placeholder)
    assert "placeholder" in str(excinfo.value)


def test_invalid_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(environment="staging")


def test_invalid_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(log_level="VERBOSE")


def test_invalid_port_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(postgres_port=0)
    with pytest.raises(ValidationError):
        make_settings(postgres_port=70000)


def test_non_positive_session_ttl_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(session_ttl_seconds=0)


def test_production_debug_is_rejected() -> None:
    with pytest.raises(ValidationError) as excinfo:
        make_settings(environment="production", debug=True)
    assert "debug" in str(excinfo.value)


def test_production_without_debug_is_accepted() -> None:
    settings = make_settings(environment="production", debug=False)
    assert settings.is_production is True


def test_get_settings_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_cache()
    monkeypatch.setenv("POSTGRES_PASSWORD", "pg" * 20)
    monkeypatch.setenv("SECRET_KEY", "sk" * 20)
    monkeypatch.setenv("INTERNAL_API_TOKEN", "tok" * 20)
    monkeypatch.setenv("ENVIRONMENT", "test")
    try:
        settings = get_settings()
        assert settings.environment is Environment.TEST
    finally:
        clear_settings_cache()


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_cache()
    monkeypatch.setenv("POSTGRES_PASSWORD", "pg" * 20)
    monkeypatch.setenv("SECRET_KEY", "sk" * 20)
    monkeypatch.setenv("INTERNAL_API_TOKEN", "tok" * 20)
    try:
        assert get_settings() is get_settings()
    finally:
        clear_settings_cache()


def test_env_file_is_relative_to_repo_not_cwd() -> None:
    from app import config

    assert config.REPO_ROOT.is_dir()
    assert config.BACKEND_DIR.is_dir()
    assert config.BACKEND_DIR.parent == config.REPO_ROOT
    assert len(config.ENV_FILES) == 2
