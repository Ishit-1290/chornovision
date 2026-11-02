"""Tests for the authentication endpoints (login, logout, me)."""

from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.security import generate_csrf_token, generate_session_token, hash_token
from app.models import User, UserSession
from app.repositories import sessions as sessions_repo
from app.utils import utcnow

SESSION_COOKIE = "chronovision_session"
CSRF_COOKIE = "chronovision_csrf"


def _login(client: TestClient, credentials: dict[str, str]):
    return client.post(
        "/api/auth/login",
        json={"username": credentials["username"], "password": credentials["password"]},
    )


def test_login_returns_user_and_sets_cookies(client: TestClient, admin_user: User) -> None:
    response = _login(client, {"username": "admin", "password": "correct-horse-battery-staple"})
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["username"] == "admin"
    assert body["user"]["is_active"] is True
    assert "password" not in response.text
    assert "password_hash" not in response.text
    assert SESSION_COOKIE in response.cookies
    assert CSRF_COOKIE in response.cookies


def test_session_cookie_is_httponly_and_csrf_cookie_is_readable(
    client: TestClient, admin_user: User
) -> None:
    response = _login(client, {"username": "admin", "password": "correct-horse-battery-staple"})
    set_cookie_headers = response.headers.get_list("set-cookie")
    session_header = next(h for h in set_cookie_headers if h.startswith(SESSION_COOKIE))
    csrf_header = next(h for h in set_cookie_headers if h.startswith(CSRF_COOKIE))
    assert "httponly" in session_header.lower()
    assert "httponly" not in csrf_header.lower()
    assert "samesite=lax" in session_header.lower()


def test_login_rejects_wrong_password(client: TestClient, admin_user: User) -> None:
    response = _login(client, {"username": "admin", "password": "wrong-password"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password"


def test_login_rejects_unknown_user(client: TestClient, admin_user: User) -> None:
    response = _login(client, {"username": "nobody", "password": "correct-horse-battery-staple"})
    assert response.status_code == 401


def test_login_rejects_inactive_user(
    client: TestClient, db_session_factory, admin_user: User
) -> None:
    db: Session = db_session_factory()
    try:
        user = db.get(User, admin_user.id)
        user.is_active = False
        db.commit()
    finally:
        db.close()
    response = _login(client, {"username": "admin", "password": "correct-horse-battery-staple"})
    assert response.status_code == 401


def test_login_requires_valid_payload(client: TestClient, admin_user: User) -> None:
    assert client.post("/api/auth/login", json={}).status_code == 422
    response = client.post("/api/auth/login", json={"username": "admin", "password": ""})
    assert response.status_code == 422


def test_me_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_current_user_after_login(client: TestClient, admin_user: User) -> None:
    _login(client, {"username": "admin", "password": "correct-horse-battery-staple"})
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json()["username"] == "admin"


def test_logout_requires_valid_csrf_token(client: TestClient, admin_user: User) -> None:
    _login(client, {"username": "admin", "password": "correct-horse-battery-staple"})
    assert client.post("/api/auth/logout").status_code == 403
    response = client.post("/api/auth/logout", headers={"X-CSRF-Token": "not-the-token"})
    assert response.status_code == 403


def test_logout_revokes_session(client: TestClient, admin_user: User) -> None:
    _login(client, {"username": "admin", "password": "correct-horse-battery-staple"})
    csrf = client.cookies.get(CSRF_COOKIE)
    response = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert response.json()["detail"] == "Logged out"
    assert client.get("/api/auth/me").status_code == 401


def test_expired_session_is_rejected(
    client: TestClient, db_session_factory, admin_user: User
) -> None:
    token = generate_session_token()
    db: Session = db_session_factory()
    try:
        db.add(
            UserSession(
                user_id=admin_user.id,
                session_token_hash=hash_token(token),
                csrf_token_hash=hash_token(generate_csrf_token()),
                expires_at=utcnow() - timedelta(seconds=1),
            )
        )
        db.commit()
    finally:
        db.close()
    client.cookies.set(SESSION_COOKIE, token)
    assert client.get("/api/auth/me").status_code == 401


def test_revoked_session_is_rejected(
    client: TestClient, db_session_factory, admin_user: User
) -> None:
    token = generate_session_token()
    db: Session = db_session_factory()
    try:
        session = UserSession(
            user_id=admin_user.id,
            session_token_hash=hash_token(token),
            csrf_token_hash=hash_token(generate_csrf_token()),
            expires_at=utcnow() + timedelta(hours=1),
        )
        db.add(session)
        db.commit()
        sessions_repo.revoke(db, session)
    finally:
        db.close()
    client.cookies.set(SESSION_COOKIE, token)
    assert client.get("/api/auth/me").status_code == 401


def test_login_is_rate_limited(client: TestClient, admin_user: User) -> None:
    for _ in range(5):
        assert _login(client, {"username": "admin", "password": "wrong"}).status_code == 401
    blocked = _login(client, {"username": "admin", "password": "wrong"})
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers


def test_successful_login_resets_rate_limit(client: TestClient, admin_user: User) -> None:
    for _ in range(4):
        assert _login(client, {"username": "admin", "password": "wrong"}).status_code == 401
    assert (
        _login(
            client, {"username": "admin", "password": "correct-horse-battery-staple"}
        ).status_code
        == 200
    )
    assert _login(client, {"username": "admin", "password": "wrong"}).status_code == 401
