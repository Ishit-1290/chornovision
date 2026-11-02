"""events, event history, and evidence metadata

Revision ID: 0003_events_evidence
Revises: 0002_cameras
Create Date: 2026-10-29

Adds the Phase 6 persistence surface:

* ``events`` — the current state of each canonical event (FR-40, FR-45).
* ``event_transitions`` — immutable lifecycle history (FR-21).
* ``evidence`` — snapshot/clip metadata with a relative path and retention status
  (FR-38, FR-41, FR-42).

The upgrade is additive; ``downgrade`` drops the three tables in reverse order.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_events_evidence"
down_revision: str | None = "0002_cameras"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=64), nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("zone_id", sa.String(length=64), nullable=True),
        sa.Column("zone_name", sa.String(length=128), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trigger_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("certainty", sa.String(length=16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column(
            "review_status", sa.String(length=16), server_default="unreviewed", nullable=False
        ),
        sa.Column("rule_version", sa.String(length=32), nullable=True),
        sa.Column("config_version", sa.String(length=32), nullable=True),
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
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_event_id", "events", ["event_id"], unique=True)
    op.create_index("ix_events_camera_id", "events", ["camera_id"], unique=False)
    op.create_index("ix_events_event_type", "events", ["event_type"], unique=False)
    op.create_index("ix_events_trigger_time", "events", ["trigger_time"], unique=False)
    op.create_index("ix_events_status", "events", ["status"], unique=False)

    op.create_table(
        "event_transitions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("state_version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("certainty", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "state_version", name="uq_event_state_version"),
    )
    op.create_index(
        "ix_event_transitions_event_id", "event_transitions", ["event_id"], unique=False
    )

    op.create_table(
        "evidence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=16), nullable=False),
        sa.Column("relative_path", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="pending", nullable=False),
        sa.Column(
            "retention_status", sa.String(length=16), server_default="retained", nullable=False
        ),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.String(length=256), nullable=True),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "media_type", name="uq_evidence_event_media"),
    )
    op.create_index("ix_evidence_event_id", "evidence", ["event_id"], unique=False)
    op.create_index("ix_evidence_captured_at", "evidence", ["captured_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_evidence_captured_at", table_name="evidence")
    op.drop_index("ix_evidence_event_id", table_name="evidence")
    op.drop_table("evidence")

    op.drop_index("ix_event_transitions_event_id", table_name="event_transitions")
    op.drop_table("event_transitions")

    op.drop_index("ix_events_status", table_name="events")
    op.drop_index("ix_events_trigger_time", table_name="events")
    op.drop_index("ix_events_event_type", table_name="events")
    op.drop_index("ix_events_camera_id", table_name="events")
    op.drop_index("ix_events_event_id", table_name="events")
    op.drop_table("events")
