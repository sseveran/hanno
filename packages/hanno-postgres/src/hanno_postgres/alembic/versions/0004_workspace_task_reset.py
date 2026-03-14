"""Reset the Postgres schema to the workspace/task model.

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-15

This migration is intentionally destructive. Existing Postgres ledger data is
not preserved for the workspace/task rollout, but the Alembic revision chain is
kept intact so previously initialized databases can still upgrade to `head`.
"""

from __future__ import annotations

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS sequence_counters;
        DROP TABLE IF EXISTS leases;
        DROP TABLE IF EXISTS approvals;
        DROP TABLE IF EXISTS artifacts;
        DROP TABLE IF EXISTS state_versions;
        DROP TABLE IF EXISTS edges;
        DROP TABLE IF EXISTS step_runs;
        DROP TABLE IF EXISTS events;
        DROP TABLE IF EXISTS task_repo_links;
        DROP TABLE IF EXISTS workspace_repos;
        DROP TABLE IF EXISTS tasks;
        DROP TABLE IF EXISTS sessions;
        DROP TABLE IF EXISTS runs;
        DROP TABLE IF EXISTS workspaces;

        CREATE TABLE workspaces (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            external_refs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            labels_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        );
        CREATE INDEX idx_workspaces_status ON workspaces(status);

        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL REFERENCES workspaces(id),
            title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            external_refs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            labels_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        );
        CREATE INDEX idx_tasks_workspace_id ON tasks(workspace_id);
        CREATE INDEX idx_tasks_status ON tasks(status);

        CREATE TABLE workspace_repos (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL REFERENCES workspaces(id),
            vcs TEXT NOT NULL DEFAULT 'git',
            display_name TEXT NOT NULL DEFAULT '',
            canonical_remote TEXT NOT NULL DEFAULT '',
            local_path TEXT,
            default_branch TEXT,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        );
        CREATE INDEX idx_workspace_repos_workspace_id ON workspace_repos(workspace_id);
        CREATE INDEX idx_workspace_repos_canonical_remote ON workspace_repos(canonical_remote);
        CREATE INDEX idx_workspace_repos_local_path ON workspace_repos(local_path);

        CREATE TABLE task_repo_links (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(id),
            workspace_repo_id TEXT NOT NULL REFERENCES workspace_repos(id),
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE(task_id, workspace_repo_id)
        );
        CREATE INDEX idx_task_repo_links_task_id ON task_repo_links(task_id);
        CREATE INDEX idx_task_repo_links_workspace_repo_id ON task_repo_links(workspace_repo_id);

        CREATE TABLE runs (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL REFERENCES workspaces(id),
            task_id TEXT REFERENCES tasks(id),
            workspace_repo_id TEXT REFERENCES workspace_repos(id),
            run_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'planned',
            title TEXT NOT NULL DEFAULT '',
            external_refs_json JSONB NOT NULL DEFAULT '[]'::jsonb,
            labels_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        );
        CREATE INDEX idx_runs_workspace_id ON runs(workspace_id);
        CREATE INDEX idx_runs_task_id ON runs(task_id);
        CREATE INDEX idx_runs_workspace_repo_id ON runs(workspace_repo_id);
        CREATE INDEX idx_runs_status ON runs(status);
        CREATE INDEX idx_runs_run_type ON runs(run_type);

        CREATE TABLE events (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            sequence INTEGER NOT NULL,
            kind TEXT NOT NULL,
            actor_json JSONB NOT NULL,
            payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            step_run_id TEXT,
            parent_event_id TEXT,
            trace_id TEXT,
            span_id TEXT,
            timestamp TIMESTAMPTZ NOT NULL,
            UNIQUE(run_id, sequence)
        );
        CREATE INDEX idx_events_run_seq ON events(run_id, sequence);
        CREATE INDEX idx_events_kind ON events(kind);

        CREATE TABLE step_runs (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            step_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            iteration INTEGER NOT NULL DEFAULT 0,
            parent_step_run_id TEXT,
            started_at TIMESTAMPTZ,
            ended_at TIMESTAMPTZ,
            summary TEXT NOT NULL DEFAULT '',
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL
        );
        CREATE INDEX idx_step_runs_run_id ON step_runs(run_id);

        CREATE TABLE edges (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            from_step_run_id TEXT NOT NULL,
            to_step_run_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
        );
        CREATE INDEX idx_edges_run_id ON edges(run_id);

        CREATE TABLE state_versions (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            sequence INTEGER NOT NULL,
            prev_state_version_id TEXT,
            state_ref TEXT NOT NULL,
            state_hash TEXT NOT NULL,
            actor_json JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL
        );
        CREATE INDEX idx_state_versions_run_id ON state_versions(run_id);

        CREATE TABLE artifacts (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            step_run_id TEXT,
            kind TEXT NOT NULL,
            uri TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            size BIGINT NOT NULL,
            content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
            name TEXT NOT NULL DEFAULT '',
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL
        );
        CREATE INDEX idx_artifacts_run_id ON artifacts(run_id);

        CREATE TABLE approvals (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            step_run_id TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            authority TEXT NOT NULL DEFAULT '',
            resource TEXT NOT NULL DEFAULT '',
            criteria_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            requested_by_json JSONB NOT NULL,
            resolved_by_json JSONB,
            reason TEXT NOT NULL DEFAULT '',
            requested_at TIMESTAMPTZ NOT NULL,
            resolved_at TIMESTAMPTZ
        );
        CREATE INDEX idx_approvals_run_id ON approvals(run_id);
        CREATE INDEX idx_approvals_status ON approvals(status);

        CREATE TABLE leases (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL REFERENCES runs(id),
            lease_token TEXT NOT NULL UNIQUE,
            owner_json JSONB NOT NULL,
            purpose TEXT NOT NULL DEFAULT '',
            acquired_at TIMESTAMPTZ NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL
        );
        CREATE INDEX idx_leases_run_id ON leases(run_id);
        CREATE INDEX idx_leases_expires_at ON leases(expires_at);

        CREATE TABLE sequence_counters (
            run_id TEXT PRIMARY KEY REFERENCES runs(id),
            current_seq INTEGER NOT NULL DEFAULT 0
        );
        """
    )


def downgrade() -> None:
    raise NotImplementedError("Workspace/task reset is intentionally irreversible.")
