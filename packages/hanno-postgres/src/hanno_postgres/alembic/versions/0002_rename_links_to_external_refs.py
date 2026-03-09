"""Rename links_json to external_refs_json.

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-07

"""

from __future__ import annotations

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE runs RENAME COLUMN links_json TO external_refs_json")


def downgrade() -> None:
    op.execute("ALTER TABLE runs RENAME COLUMN external_refs_json TO links_json")
