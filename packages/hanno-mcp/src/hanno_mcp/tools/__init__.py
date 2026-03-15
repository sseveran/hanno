"""Tool registration for the Hanno MCP server."""

from mcp.server.fastmcp import FastMCP

from . import approvals, artifacts, events, runs, search, sessions, steps


def register_all_tools(mcp: FastMCP) -> None:
    """Register all Hanno tools on the MCP server."""
    sessions.register(mcp)
    runs.register(mcp)
    steps.register(mcp)
    events.register(mcp)
    artifacts.register(mcp)
    approvals.register(mcp)
    search.register(mcp)
