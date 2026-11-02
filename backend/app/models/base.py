"""Declarative base for all ChronoVision ORM models."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for ChronoVision ORM models.

    ``Base.metadata`` is the target metadata used by Alembic migrations.
    """
