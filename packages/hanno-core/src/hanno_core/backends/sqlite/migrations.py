"""SQLite schema definitions and migration runner."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

SCHEMA_VERSION = 3

MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY,
        run_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'planned',
        title TEXT NOT NULL DEFAULT '',
        links_json TEXT NOT NULL DEFAULT '[]',
        labels_json TEXT NOT NULL DEFAULT '{}',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);
    CREATE INDEX IF NOT EXISTS idx_runs_run_type ON runs(run_type);

    CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(id),
        sequence INTEGER NOT NULL,
        kind TEXT NOT NULL,
        actor_json TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}',
        step_run_id TEXT,
        parent_event_id TEXT,
        trace_id TEXT,
        span_id TEXT,
        timestamp TEXT NOT NULL,
        UNIQUE(run_id, sequence)
    );
    CREATE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, sequence);
    CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);

    CREATE TABLE IF NOT EXISTS step_runs (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(id),
        step_name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'queued',
        iteration INTEGER NOT NULL DEFAULT 0,
        parent_step_run_id TEXT,
        started_at TEXT,
        ended_at TEXT,
        summary TEXT NOT NULL DEFAULT '',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_step_runs_run_id ON step_runs(run_id);

    CREATE TABLE IF NOT EXISTS edges (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(id),
        from_step_run_id TEXT NOT NULL,
        to_step_run_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_edges_run_id ON edges(run_id);

    CREATE TABLE IF NOT EXISTS state_versions (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(id),
        sequence INTEGER NOT NULL,
        prev_state_version_id TEXT,
        state_ref TEXT NOT NULL,
        state_hash TEXT NOT NULL,
        actor_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_state_versions_run_id ON state_versions(run_id);

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
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_artifacts_run_id ON artifacts(run_id);

    CREATE TABLE IF NOT EXISTS approvals (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(id),
        step_run_id TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        authority TEXT NOT NULL DEFAULT '',
        resource TEXT NOT NULL DEFAULT '',
        criteria_json TEXT NOT NULL DEFAULT '{}',
        requested_by_json TEXT NOT NULL,
        resolved_by_json TEXT,
        reason TEXT NOT NULL DEFAULT '',
        requested_at TEXT NOT NULL,
        resolved_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_approvals_run_id ON approvals(run_id);
    CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);

    CREATE TABLE IF NOT EXISTS leases (
        id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(id),
        lease_token TEXT NOT NULL UNIQUE,
        owner_json TEXT NOT NULL,
        purpose TEXT NOT NULL DEFAULT '',
        acquired_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_leases_run_id ON leases(run_id);
    CREATE INDEX IF NOT EXISTS idx_leases_expires_at ON leases(expires_at);

    CREATE TABLE IF NOT EXISTS sequence_counters (
        run_id TEXT PRIMARY KEY REFERENCES runs(id),
        current_seq INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    );
    """,
    2: """
    ALTER TABLE runs RENAME COLUMN links_json TO external_refs_json;
    """,
    3: """
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active',
        external_refs_json TEXT NOT NULL DEFAULT '[]',
        labels_json TEXT NOT NULL DEFAULT '{}',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);

    ALTER TABLE runs ADD COLUMN session_id TEXT;
    CREATE INDEX IF NOT EXISTS idx_runs_session_id ON runs(session_id);
    """,
}


async def run_migrations(conn: aiosqlite.Connection) -> None:
    """Apply any pending migrations."""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    await conn.commit()

    cursor = await conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
    )
    row = await cursor.fetchone()
    current_version = row[0] if row else 0

    for version in sorted(MIGRATIONS.keys()):
        if version > current_version:
            await conn.executescript(MIGRATIONS[version])
            await conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) "
                "VALUES (?, datetime('now'))",
                (version,),
            )
            await conn.commit()
