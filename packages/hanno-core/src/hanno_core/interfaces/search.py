"""SearchIndexer protocol — optional search integration."""

from __future__ import annotations

from typing import Protocol


class SearchDocument:
    """A document to be indexed for search."""

    def __init__(
        self,
        *,
        doc_type: str,
        run_id: str,
        content: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.doc_type = doc_type
        self.run_id = run_id
        self.content = content
        self.metadata = metadata or {}


class SearchIndexer(Protocol):
    """Optional search backend for indexing ledger content."""

    async def ingest_document(self, doc: SearchDocument) -> None: ...

    async def delete_run(self, run_id: str) -> None: ...
