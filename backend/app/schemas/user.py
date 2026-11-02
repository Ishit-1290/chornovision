"""User-facing schemas. Password hashes are never exposed."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserRead(BaseModel):
    """Public representation of a user account."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    is_active: bool
    created_at: datetime
