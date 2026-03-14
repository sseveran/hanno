"""Shared fixtures for hanno-postgres tests."""

import pytest
from hanno_postgres.storage import PostgresStorageBackend, _run_alembic_upgrade
from testcontainers.postgres import PostgresContainer

TABLES = [
    "task_repo_links",
    "workspace_repos",
    "tasks",
    "workspaces",
    "leases",
    "approvals",
    "artifacts",
    "state_versions",
    "edges",
    "step_runs",
    "events",
    "sequence_counters",
    "runs",
]


@pytest.fixture(scope="session")
def postgres_dsn():
    with PostgresContainer("postgres:16-alpine") as pg:
        dsn = pg.get_connection_url().replace("+psycopg2", "")
        # Run Alembic migrations once for the entire test session
        _run_alembic_upgrade(dsn)
        yield dsn


@pytest.fixture
async def storage(postgres_dsn):
    s = PostgresStorageBackend(postgres_dsn, min_size=1, max_size=5)
    await s._create_pool()
    # Truncate before test so a previous failure doesn't leave dirty data
    async with s._db.acquire() as conn:
        for table in TABLES:
            await conn.execute(f"TRUNCATE {table} CASCADE")
    yield s
    await s.close()
