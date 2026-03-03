"""Hanno MCP server entry point."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from hanno_mcp.config import open_ledger
from hanno_mcp.tools import register_all_tools

mcp = FastMCP("hanno")

register_all_tools(mcp)


# --- Resources ---


@mcp.resource("hanno://runs/{run_id}")
async def get_run_resource(run_id: str) -> str:
    """Get run detail including its steps as JSON."""
    async with open_ledger() as ledger:
        run = await ledger.get_run(run_id)
        if run is None:
            return '{"error": "Run not found"}'
        steps = await ledger.list_steps(run_id)
        return (
            '{"run":'
            + run.model_dump_json()
            + ',"steps":['
            + ",".join(s.model_dump_json() for s in steps)
            + "]}"
        )


@mcp.resource("hanno://runs/{run_id}/transcript")
async def get_run_transcript(run_id: str) -> str:
    """Get the full event transcript for a run as JSON."""
    async with open_ledger() as ledger:
        run = await ledger.get_run(run_id)
        if run is None:
            return '{"error": "Run not found"}'
        events = await ledger.list_events(run_id)
        return "[" + ",".join(e.model_dump_json() for e in events) + "]"


def main() -> None:
    """Run the Hanno MCP server on stdio transport."""
    mcp.run(transport="stdio")
