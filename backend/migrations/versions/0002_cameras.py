"""cameras: configuration and lifecycle state

Revision ID: 0002_cameras
Revises: 0001_initial_auth
Create Date: 2026-10-29

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_cameras"
down_revision: str | None = "0001_initial_auth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cameras",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("stream_reference", sa.String(length=2048), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="configured", nullable=False),
        sa.Column(
            "configuration",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cameras_name", "cameras", ["name"], unique=True)
    op.create_index("ix_cameras_status", "cameras", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_cameras_status", table_name="cameras")
    op.drop_index("ix_cameras_name", table_name="cameras")
    op.drop_table("cameras")
