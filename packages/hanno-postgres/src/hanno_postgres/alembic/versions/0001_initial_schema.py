"""Initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-03-04

"""

from __future__ import annotations

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            run_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'planned',
            title TEXT NOT NULL DEFAULT '',
            links_json JSONB NOT NULL DEFAULT '[]',
            labels_json JSONB NOT NULL DEFAULT '{}',
            metadata_json JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_runs_run_type ON runs(run_type)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            sequence INTEGER NOT NULL,
            kind TEXT NOT NULL,
            actor_json JSONB NOT NULL,
            payload_json JSONB NOT NULL DEFAULT '{}',
            step_run_id TEXT,
            parent_event_id TEXT,
            trace_id TEXT,
            span_id TEXT,
            timestamp TIMESTAMPTZ NOT NULL,
            UNIQUE(run_id, sequence)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, sequence)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS step_runs (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            step_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            iteration INTEGER NOT NULL DEFAULT 0,
            parent_step_run_id TEXT,
            started_at TIMESTAMPTZ,
            ended_at TIMESTAMPTZ,
            summary TEXT NOT NULL DEFAULT '',
            metadata_json JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_step_runs_run_id ON step_runs(run_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS edges (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            from_step_run_id TEXT NOT NULL,
            to_step_run_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            metadata_json JSONB NOT NULL DEFAULT '{}'
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_edges_run_id ON edges(run_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS state_versions (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            sequence INTEGER NOT NULL,
            prev_state_version_id TEXT,
            state_ref TEXT NOT NULL,
            state_hash TEXT NOT NULL,
            actor_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_state_versions_run_id ON state_versions(run_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            step_run_id TEXT,
            kind TEXT NOT NULL,
            uri TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            size INTEGER NOT NULL,
            content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
            name TEXT NOT NULL DEFAULT '',
            metadata_json JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_artifacts_run_id ON artifacts(run_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS approvals (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            step_run_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            authority TEXT NOT NULL DEFAULT '',
            resource TEXT NOT NULL DEFAULT '',
            criteria_json JSONB NOT NULL DEFAULT '{}',
            requested_by_json JSONB NOT NULL,
            resolved_by_json JSONB,
            reason TEXT NOT NULL DEFAULT '',
            requested_at TIMESTAMPTZ NOT NULL,
            resolved_at TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_approvals_run_id ON approvals(run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS leases (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            lease_token TEXT NOT NULL UNIQUE,
            owner_json JSONB NOT NULL,
            purpose TEXT NOT NULL DEFAULT '',
            acquired_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_leases_run_id ON leases(run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_leases_expires_at ON leases(expires_at)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sequence_counters (
            run_id TEXT PRIMARY KEY REFERENCES runs(id),
            current_seq INTEGER NOT NULL DEFAULT 0
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sequence_counters")
    op.execute("DROP TABLE IF EXISTS leases")
    op.execute("DROP TABLE IF EXISTS approvals")
    op.execute("DROP TABLE IF EXISTS artifacts")
    op.execute("DROP TABLE IF EXISTS state_versions")
    op.execute("DROP TABLE IF EXISTS edges")
    op.execute("DROP TABLE IF EXISTS step_runs")
    op.execute("DROP TABLE IF EXISTS events")
    op.execute("DROP TABLE IF EXISTS runs")
