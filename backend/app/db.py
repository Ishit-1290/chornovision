"""Database engine, session factory, and FastAPI session dependency.

Engine construction is lazy so the application can start (and unit tests can run)
without a reachable PostgreSQL server. ``get_db`` is the single dependency used by
request handlers; tests override it with an in-memory database.
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create (once) the SQLAlchemy engine from the validated settings."""
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Create (once) the session factory bound to the application engine."""
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a short-lived database session."""
    db = get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def dispose_engine() -> None:
    """Dispose the engine and clear caches (used on shutdown and in tests)."""
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_session_factory.cache_clear()
    get_engine.cache_clear()
