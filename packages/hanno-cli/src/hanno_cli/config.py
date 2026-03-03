"""CLI configuration — defaults, env vars, and ledger factory."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import wraps
from pathlib import Path
from typing import Any

from hanno_core.backends.sqlite.storage import SqliteStorageBackend
from hanno_core.engine.ledger import RunLedger
from hanno_core.stores.local_fs import LocalFsArtifactStore

DEFAULT_HANNO_DIR = Path.home() / ".hanno"
DEFAULT_DB_PATH = DEFAULT_HANNO_DIR / "hanno.db"
DEFAULT_ARTIFACT_PATH = DEFAULT_HANNO_DIR / "artifacts"


def get_db_path() -> Path:
    return Path(os.environ.get("HANNO_DB_PATH", str(DEFAULT_DB_PATH)))


def get_artifact_path() -> Path:
    return Path(os.environ.get("HANNO_ARTIFACT_PATH", str(DEFAULT_ARTIFACT_PATH)))


@asynccontextmanager
async def open_ledger() -> AsyncIterator[RunLedger]:
    """Create a configured RunLedger and ensure cleanup."""
    db_path = get_db_path()
    artifact_path = get_artifact_path()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.mkdir(parents=True, exist_ok=True)

    storage = SqliteStorageBackend(db_path)
    artifacts = LocalFsArtifactStore(artifact_path)
    await storage.initialize()
    try:
        yield RunLedger(storage, artifacts)
    finally:
        await storage.close()


def async_command(f: Any) -> Any:
    """Decorator to run an async function as a typer command."""

    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(f(*args, **kwargs))

    return wrapper
