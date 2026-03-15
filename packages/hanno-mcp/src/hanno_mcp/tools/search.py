"""MCP tools for search operations."""

from __future__ import annotations

import json

from hanno_core.models.search import EntityType, SearchMode
from mcp.server.fastmcp import FastMCP

from hanno_mcp.config import open_ledger


def _error(message: str) -> str:
    return json.dumps({"error": message})


def register(mcp: FastMCP) -> None:
    """Register search tools on the MCP server."""

    @mcp.tool()
    async def hanno_search_ledger(
        query: str,
        entity_types: list[str] | None = None,
        run_id: str | None = None,
        run_type: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> str:
        """Search the workflow ledger using full-text search.

        Args:
            query: Search query text.
            entity_types: Optional list of entity types to search
                (run, event, step_run, artifact).
            run_id: Optional run ID to scope the search.
            run_type: Optional run type filter.
            status: Optional status filter.
            limit: Maximum number of results (default 20).
        """
        async with open_ledger() as ledger:
            if ledger.search is None:
                return _error("Search is not enabled")

            try:
                types = {EntityType(t) for t in entity_types} if entity_types else None
            except ValueError as exc:
                return _error(f"Invalid entity type: {exc.args[0]!s}")

            results = await ledger.search.search(
                query,
                mode=SearchMode.KEYWORD,
                entity_types=types,
                run_id=run_id,
                run_type=run_type,
                status=status,
                limit=limit,
            )

            return json.dumps(
                [r.model_dump() for r in results],
                default=str,
            )
