"""Shared test fixtures.

Environment variables are set before importing the application so the validated
settings load without a real ``.env`` and without a running PostgreSQL server. Every
API test runs against an in-memory SQLite database via a dependency override.
"""

from __future__ import annotations

import os

# Values the application needs to import without a real ``.env`` or a running
# PostgreSQL server. They are present only long enough to import the app modules;
# the autouse ``_isolated_environment`` fixture then removes them for each test so
# that configuration tests see a clean process environment.
_TEST_ENV = {
    "POSTGRES_PASSWORD": "test-postgres-password-" + "x" * 24,
    "SECRET_KEY": "test-secret-key-" + "y" * 32,
    "INTERNAL_API_TOKEN": "test-internal-token-" + "z" * 32,
    "ENVIRONMENT": "test",
}

for _key, _value in _TEST_ENV.items():
    os.environ.setdefault(_key, _value)

# Tests must never read the developer's real ``.env``: configuration is supplied only
# through the process environment (or explicit ``Settings(_env_file=None, ...)``). Without
# this, a locally enabled flag (e.g. ``LIVE_PLAYBACK_ENABLED=true``) would silently change
# test outcomes depending on the machine the suite runs on.
import app.config as _config  # noqa: E402

_config.Settings.model_config["env_file"] = ()  # type: ignore[index]

from collections.abc import Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.auth.dependencies import reset_login_limiter  # noqa: E402
from app.auth.security import hash_password  # noqa: E402
from app.config import clear_settings_cache  # noqa: E402
from app.db import get_db  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.models import Base, User  # noqa: E402
from app.services.event_broadcaster import reset_event_broadcaster  # noqa: E402
from app.services.monitoring_service import reset_monitoring_controller  # noqa: E402
from app.services.worker_registry import reset_worker_registry  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_environment() -> Iterator[None]:
    """Remove the test environment variables around each test.

    Phase 1 configuration tests assert behaviour with no environment variables set,
    so the variables needed to import the application are restored only by the
    fixtures that actually exercise the app (``client``, ``admin_env``).
    """
    saved = {key: os.environ.pop(key, None) for key in _TEST_ENV}
    clear_settings_cache()
    reset_login_limiter()
    reset_monitoring_controller()
    reset_worker_registry()
    reset_event_broadcaster()
    try:
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        clear_settings_cache()
        reset_login_limiter()
        reset_monitoring_controller()
        reset_worker_registry()
        reset_event_broadcaster()


@pytest.fixture
def admin_env() -> Iterator[None]:
    """Provide the test settings needed by non-HTTP tests that read configuration."""
    for key, value in _TEST_ENV.items():
        os.environ.setdefault(key, value)
    clear_settings_cache()
    try:
        yield
    finally:
        for key in _TEST_ENV:
            os.environ.pop(key, None)
        clear_settings_cache()


@pytest.fixture
def db_engine():
    """A fresh in-memory SQLite engine with the schema created."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def db_session_factory(db_engine) -> sessionmaker[Session]:
    """A session factory bound to the in-memory test database."""
    return sessionmaker(bind=db_engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def client(db_session_factory, admin_env) -> Iterator[TestClient]:
    """A TestClient whose ``get_db`` dependency uses the in-memory database."""

    def override_get_db() -> Iterator[Session]:
        db = db_session_factory()
        try:
            yield db
        finally:
            db.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(fastapi_app) as test_client:
            yield test_client
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.fixture
def admin_credentials() -> dict[str, str]:
    return {"username": "admin", "password": "correct-horse-battery-staple"}


@pytest.fixture
def admin_user(db_session_factory, admin_credentials) -> User:
    db: Session = db_session_factory()
    try:
        user = User(
            username=admin_credentials["username"],
            password_hash=hash_password(admin_credentials["password"]),
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db.close()


@pytest.fixture
def auth_client(client: TestClient, admin_user: User, admin_credentials) -> TestClient:
    """A TestClient logged in as the administrator (session cookies set)."""
    response = client.post(
        "/api/auth/login",
        json={"username": admin_credentials["username"], "password": admin_credentials["password"]},
    )
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
def csrf_headers(auth_client: TestClient) -> dict[str, str]:
    """CSRF header matching the authenticated session's CSRF cookie."""
    return {"X-CSRF-Token": auth_client.cookies.get("chronovision_csrf")}


@pytest.fixture
def evidence_dir(tmp_path, admin_env) -> Iterator:
    """Point ``EVIDENCE_DIR`` at a per-test temporary directory."""
    os.environ["EVIDENCE_DIR"] = str(tmp_path)
    clear_settings_cache()
    try:
        yield tmp_path
    finally:
        os.environ.pop("EVIDENCE_DIR", None)
        clear_settings_cache()
