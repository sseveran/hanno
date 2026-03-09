"""MCP tools for session lifecycle operations."""

from __future__ import annotations

from hanno_core.engine.ledger import InvalidTransitionError, LedgerError
from hanno_core.models import ExternalRef
from mcp.server.fastmcp import FastMCP

from hanno_mcp.config import open_ledger


def register(mcp: FastMCP) -> None:
    """Register session tools on the MCP server."""

    @mcp.tool()
    async def hanno_create_session(
        title: str = "",
        labels: dict[str, str] | None = None,
        external_refs: list[dict[str, str]] | None = None,
    ) -> str:
        """Create a new session to group related runs.

        Args:
            title: Optional human-readable title.
            labels: Optional key-value labels for filtering.
            external_refs: Optional list of external references, each with
                system, ref_type, ref_id, and optional url.
        """
        refs = [ExternalRef(**r) for r in external_refs] if external_refs else None
        async with open_ledger() as ledger:
            try:
                session = await ledger.create_session(
                    title=title,
                    labels=labels,
                    external_refs=refs,
                )
                return session.model_dump_json()
            except LedgerError as e:
                return _error(str(e))

    @mcp.tool()
    async def hanno_get_session(session_id: str) -> str:
        """Get details of a specific session.

        Args:
            session_id: The session ID (ULID).
        """
        async with open_ledger() as ledger:
            session = await ledger.get_session(session_id)
            if session is None:
                return _error(f"Session not found: {session_id}")
            return session.model_dump_json()

    @mcp.tool()
    async def hanno_list_sessions(
        status: str | None = None,
        limit: int = 50,
    ) -> str:
        """List sessions, optionally filtered by status.

        Args:
            status: Filter by session status (active, closed, archived).
            limit: Max number of sessions to return (default 50).
        """
        from hanno_core.models import SessionStatus

        async with open_ledger() as ledger:
            kwargs: dict[str, object] = {"limit": limit}
            if status is not None:
                try:
                    kwargs["status"] = SessionStatus(status)
                except ValueError:
                    return _error(f"Invalid status: {status}")
            sessions = await ledger.list_sessions(**kwargs)
            return "[" + ",".join(s.model_dump_json() for s in sessions) + "]"

    @mcp.tool()
    async def hanno_close_session(session_id: str) -> str:
        """Close an active session.

        Args:
            session_id: The session ID (ULID).
        """
        async with open_ledger() as ledger:
            try:
                session = await ledger.close_session(session_id)
                return session.model_dump_json()
            except (LedgerError, InvalidTransitionError) as e:
                return _error(str(e))

    @mcp.tool()
    async def hanno_find_session_by_ref(
        system: str,
        ref_type: str,
        ref_id: str,
    ) -> str:
        """Find sessions by external reference (e.g. GitHub PR).

        Args:
            system: External system (e.g. 'github').
            ref_type: Reference type (e.g. 'pr').
            ref_id: Reference ID (e.g. 'org/repo#42').
        """
        async with open_ledger() as ledger:
            sessions = await ledger.find_sessions_by_external_ref(
                system=system, ref_type=ref_type, ref_id=ref_id
            )
            return "[" + ",".join(s.model_dump_json() for s in sessions) + "]"

    @mcp.tool()
    async def hanno_list_session_runs(
        session_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> str:
        """List all runs belonging to a session.

        Args:
            session_id: The session ID (ULID).
            status: Optional filter by run status.
            limit: Max number of runs to return (default 50).
        """
        from hanno_core.models import RunStatus

        async with open_ledger() as ledger:
            kwargs: dict[str, object] = {"limit": limit}
            if status is not None:
                try:
                    kwargs["status"] = RunStatus(status)
                except ValueError:
                    return _error(f"Invalid status: {status}")
            runs = await ledger.list_session_runs(session_id, **kwargs)
            return "[" + ",".join(r.model_dump_json() for r in runs) + "]"


def _error(message: str) -> str:
    """Return a JSON error response."""
    import json

    return json.dumps({"error": message})
