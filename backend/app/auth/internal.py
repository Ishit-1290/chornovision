"""Internal worker→backend authentication (OQ-09, D-12).

Internal endpoints are separate from the cookie-authenticated user API. They require a
shared secret in ``X-Internal-Token`` that is compared in **constant time** and is required
even on localhost. The token is never logged, echoed, or included in an error response.
"""

from __future__ import annotations

from fastapi import HTTPException, Request, status

from app.auth.security import tokens_equal
from app.config import get_settings

INTERNAL_TOKEN_HEADER = "X-Internal-Token"


def require_internal_token(request: Request) -> None:
    """Reject the request unless it carries the configured internal token."""
    presented = request.headers.get(INTERNAL_TOKEN_HEADER, "")
    expected = get_settings().internal_api_token.get_secret_value()
    if not presented or not tokens_equal(presented, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing internal token",
        )
