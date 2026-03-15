"""CLI configuration — defaults, env vars, and ledger factory."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import wraps
from pathlib import Path
from typing import Any

from hanno_core.backends.sqlite.search import SqliteFtsSearchBackend
from hanno_core.backends.sqlite.storage import SqliteStorageBackend
from hanno_core.engine.ledger import RunLedger
from hanno_core.hooks.registry import InProcessHookRegistry
from hanno_core.hooks.search import SearchIndexerHook
from hanno_core.stores.local_fs import LocalFsArtifactStore

DEFAULT_HANNO_DIR = Path.home() / ".hanno"
DEFAULT_DB_PATH = DEFAULT_HANNO_DIR / "hanno.db"
DEFAULT_ARTIFACT_PATH = DEFAULT_HANNO_DIR / "artifacts"


def get_db_path() -> Path:
    return Path(os.environ.get("HANNO_DB_PATH", str(DEFAULT_DB_PATH)))


def get_artifact_path() -> Path:
    return Path(os.environ.get("HANNO_ARTIFACT_PATH", str(DEFAULT_ARTIFACT_PATH)))


def _search_enabled() -> bool:
    return os.environ.get("HANNO_SEARCH_ENABLED", "true").lower() in ("true", "1", "yes")


@asynccontextmanager
async def open_ledger() -> AsyncIterator[RunLedger]:
    """Create a configured RunLedger and ensure cleanup."""
    db_path = get_db_path()
    artifact_path = get_artifact_path()

    db_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.mkdir(parents=True, exist_ok=True)

    storage = SqliteStorageBackend(db_path)
    artifacts = LocalFsArtifactStore(artifact_path)
    storage_initialized = False
    search = None
    try:
        await storage.initialize()
        storage_initialized = True

        if _search_enabled():
            search = SqliteFtsSearchBackend(db_path)
            await search.initialize()

        hooks = InProcessHookRegistry()
        if search is not None:
            hooks.register(SearchIndexerHook(search, storage, artifacts))

        yield RunLedger(storage, artifacts, hooks=hooks, search=search)
    finally:
        if search is not None:
            await search.close()
        if storage_initialized:
            await storage.close()


def async_command(f: Any) -> Any:
    """Decorator to run an async function as a typer command."""

    @wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(f(*args, **kwargs))

    return wrapper
