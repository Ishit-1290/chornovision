"""encrypted per-camera stream credentials

Revision ID: 0004_camera_stream_credentials
Revises: 0003_events_evidence
Create Date: 2026-11-01

Adds one nullable column, ``cameras.stream_credentials_encrypted``, holding a
Fernet-encrypted ``{"username", "password"}`` JSON document (D-64). The column is
additive and nullable, so existing rows and the Phase 1–9 behaviour are unchanged when
it is ``NULL``.

**Downgrade destroys stored credentials** (they are not recoverable from anywhere else);
this is documented in ``docs/LIVE_PLAYBACK.md``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_camera_stream_credentials"
down_revision: str | None = "0003_events_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cameras",
        sa.Column("stream_credentials_encrypted", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cameras", "stream_credentials_encrypted")
