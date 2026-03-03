"""MCP tools for event operations."""

from __future__ import annotations

from hanno_core.engine.ledger import LedgerError
from hanno_core.models.identity import ActorRef
from mcp.server.fastmcp import FastMCP

from hanno_mcp.config import open_ledger

ACTOR = ActorRef(provider="mcp", identifier="agent")


def register(mcp: FastMCP) -> None:
    """Register event tools on the MCP server."""

    @mcp.tool()
    async def hanno_list_events(
        run_id: str,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> str:
        """List events for a run, optionally starting after a given sequence number.

        Args:
            run_id: The run ID (ULID).
            after_sequence: Only return events after this sequence number (default 0).
            limit: Max number of events to return.
        """
        async with open_ledger() as ledger:
            kwargs: dict[str, object] = {"after_sequence": after_sequence}
            if limit is not None:
                kwargs["limit"] = limit
            events = await ledger.list_events(run_id, **kwargs)
            return "[" + ",".join(e.model_dump_json() for e in events) + "]"

    @mcp.tool()
    async def hanno_add_note(
        run_id: str,
        message: str,
        step_run_id: str | None = None,
    ) -> str:
        """Add a freeform note to a run's event log.

        Args:
            run_id: The run ID (ULID).
            message: The note message.
            step_run_id: Optional step run ID to associate the note with.
        """
        async with open_ledger() as ledger:
            try:
                event = await ledger.add_note(
                    run_id, actor=ACTOR, message=message, step_run_id=step_run_id
                )
                return event.model_dump_json()
            except LedgerError as e:
                return _error(str(e))


def _error(message: str) -> str:
    import json

    return json.dumps({"error": message})
