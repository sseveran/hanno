"""Add sessions table and session_id to runs.

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-08

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column(
            "external_refs_json",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "labels_json",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "metadata_json",
            sa.dialects.postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
    )
    op.create_index("idx_sessions_status", "sessions", ["status"])

    op.add_column("runs", sa.Column("session_id", sa.Text(), nullable=True))
    op.create_index("idx_runs_session_id", "runs", ["session_id"])


def downgrade() -> None:
    op.drop_index("idx_runs_session_id", table_name="runs")
    op.drop_column("runs", "session_id")
    op.drop_index("idx_sessions_status", table_name="sessions")
    op.drop_table("sessions")
