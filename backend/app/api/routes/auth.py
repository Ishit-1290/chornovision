"""Authentication endpoints: login, logout, and current-user lookup."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.auth.cookies import clear_auth_cookies, set_csrf_cookie, set_session_cookie
from app.auth.dependencies import (
    AuthContext,
    enforce_csrf,
    get_auth_context,
    get_current_user,
    get_login_limiter,
)
from app.auth.rate_limit import login_rate_limit_key
from app.db import get_db
from app.models.user import User
from app.repositories import audit as audit_repo
from app.schemas.auth import LoginRequest, LoginResponse, MessageResponse
from app.schemas.user import UserRead
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> LoginResponse:
    """Authenticate and establish a server-side session."""
    limiter = get_login_limiter()
    key = login_rate_limit_key(request.client.host if request.client else None, payload.username)
    if not limiter.allow(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(limiter.retry_after(key))},
        )

    user = auth_service.authenticate(db, payload.username, payload.password)
    if user is None:
        limiter.record_failure(key)
        audit_repo.record(db, action="login_failed", resource_type="auth")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    limiter.reset(key)
    raw_token, csrf_token, session = auth_service.create_session(db, user)
    set_session_cookie(response, raw_token, session.expires_at)
    set_csrf_cookie(response, csrf_token)
    audit_repo.record(
        db,
        action="login",
        user_id=user.id,
        resource_type="session",
        resource_id=str(session.id),
    )
    return LoginResponse(user=UserRead.model_validate(user), expires_at=session.expires_at)


@router.post("/logout", response_model=MessageResponse)
def logout(
    request: Request,
    response: Response,
    auth: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Revoke the current session. Requires a valid CSRF token."""
    enforce_csrf(request, auth.session)
    auth_service.revoke_session(db, auth.session)
    audit_repo.record(
        db,
        action="logout",
        user_id=auth.user.id,
        resource_type="session",
        resource_id=str(auth.session.id),
    )
    clear_auth_cookies(response)
    return MessageResponse(detail="Logged out")


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)) -> User:
    """Return the currently authenticated user."""
    return user
