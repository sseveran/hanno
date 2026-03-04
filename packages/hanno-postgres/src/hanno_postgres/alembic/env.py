"""Alembic environment for hanno-postgres.

Uses sqlalchemy[asyncio] + asyncpg so no extra sync driver is required.
The database URL is set programmatically via AlembicConfig.set_main_option,
or via the HANNO_POSTGRES_DSN env var when using the Alembic CLI directly.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _get_url() -> str:
    """Return the SQLAlchemy-format database URL."""
    # Prefer programmatic config (set by _run_alembic_upgrade)
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    # Fall back to env var for CLI usage
    dsn = os.environ.get("HANNO_POSTGRES_DSN", "")
    if not dsn:
        msg = (
            "Database URL not configured. Set HANNO_POSTGRES_DSN or "
            "pass sqlalchemy.url via AlembicConfig."
        )
        raise RuntimeError(msg)
    # Convert to SQLAlchemy asyncpg dialect
    if dsn.startswith("postgres://"):
        dsn = "postgresql+asyncpg://" + dsn[len("postgres://"):]
    elif dsn.startswith("postgresql://"):
        dsn = "postgresql+asyncpg://" + dsn[len("postgresql://"):]
    return dsn


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection."""
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection):  # type: ignore[no-untyped-def]
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations against a live DB using asyncpg."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
