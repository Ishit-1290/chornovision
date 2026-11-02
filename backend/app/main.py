"""FastAPI application entry point.

``app`` is the ASGI application used by ``uvicorn app.main:app``. The database engine
is created lazily on first use, so importing this module does not require a reachable
PostgreSQL server.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.router import api_router
from app.config import get_settings
from app.db import dispose_engine


def configure_logging(level: str) -> None:
    """Configure root logging once."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Release the database engine on shutdown."""
    yield
    dispose_engine()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    settings = get_settings()
    configure_logging(settings.log_level.value)

    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
