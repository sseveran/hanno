"""SearchBackend protocol — optional search integration for the workflow ledger."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from hanno_core.models import (
    Artifact,
    Event,
    Run,
    StepRun,
)
from hanno_core.models.search import EntityType, SearchMode, SearchResult


class SearchBackend(Protocol):
    """Pluggable search backend for indexing and querying ledger content.

    Implementations may support keyword search (FTS), vector search
    (embeddings), or both (hybrid with Reciprocal Rank Fusion).
    """

    async def initialize(self) -> None: ...

    async def close(self) -> None: ...

    # --- Indexing (called by SearchIndexerHook on writes) ---

    async def index_run(self, run: Run) -> None: ...

    async def index_event(self, event: Event) -> None: ...

    async def index_step_run(self, step: StepRun) -> None: ...

    async def index_artifact(
        self, artifact: Artifact, content: bytes | None = None
    ) -> None: ...

    async def delete_run(self, run_id: str) -> None: ...

    # --- Querying ---

    async def search(
        self,
        query: str,
        *,
        mode: SearchMode = SearchMode.KEYWORD,
        entity_types: set[EntityType] | None = None,
        run_id: str | None = None,
        run_type: str | None = None,
        status: str | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
        labels: dict[str, str] | None = None,
        limit: int = 20,
    ) -> list[SearchResult]: ...

    async def find_similar(
        self,
        entity_type: EntityType,
        entity_id: str,
        *,
        limit: int = 10,
    ) -> list[SearchResult]: ...
