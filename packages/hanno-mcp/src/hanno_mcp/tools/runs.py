"""MCP tools for run lifecycle operations."""

from __future__ import annotations

from hanno_core.engine.ledger import InvalidTransitionError, LedgerError
from hanno_core.models import ExternalRef
from hanno_core.models.identity import ActorRef
from mcp.server.fastmcp import FastMCP

from hanno_mcp.config import open_ledger

ACTOR = ActorRef(provider="mcp", identifier="agent")


def register(mcp: FastMCP) -> None:
    """Register run tools on the MCP server."""

    @mcp.tool()
    async def hanno_create_run(
        run_type: str,
        title: str = "",
        labels: dict[str, str] | None = None,
        external_refs: list[dict[str, str]] | None = None,
        session_id: str | None = None,
    ) -> str:
        """Create a new workflow run.

        Args:
            run_type: Type of workflow (e.g. 'deploy', 'build', 'review').
            title: Optional human-readable title.
            labels: Optional key-value labels for filtering.
            external_refs: Optional list of external references, each with
                system, ref_type, ref_id, and optional url.
            session_id: Optional session ID to associate this run with.
        """
        refs = [ExternalRef(**r) for r in external_refs] if external_refs else None
        async with open_ledger() as ledger:
            try:
                run = await ledger.create_run(
                    run_type,
                    actor=ACTOR,
                    title=title,
                    labels=labels,
                    external_refs=refs,
                    session_id=session_id,
                )
                return run.model_dump_json()
            except LedgerError as e:
                return _error(str(e))

    @mcp.tool()
    async def hanno_list_runs(
        status: str | None = None,
        run_type: str | None = None,
        limit: int = 50,
    ) -> str:
        """List workflow runs, optionally filtered by status or type.

        Args:
            status: Filter by run status (planned, running, succeeded, failed, canceled).
            run_type: Filter by run type.
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
            if run_type is not None:
                kwargs["run_type"] = run_type
            runs = await ledger.list_runs(**kwargs)
            return "[" + ",".join(r.model_dump_json() for r in runs) + "]"

    @mcp.tool()
    async def hanno_get_run(run_id: str) -> str:
        """Get details of a specific run.

        Args:
            run_id: The run ID (ULID).
        """
        async with open_ledger() as ledger:
            run = await ledger.get_run(run_id)
            if run is None:
                return _error(f"Run not found: {run_id}")
            return run.model_dump_json()

    @mcp.tool()
    async def hanno_start_run(run_id: str) -> str:
        """Start a planned run, transitioning it to 'running' status.

        Args:
            run_id: The run ID (ULID).
        """
        async with open_ledger() as ledger:
            try:
                run = await ledger.start_run(run_id, actor=ACTOR)
                return run.model_dump_json()
            except (LedgerError, InvalidTransitionError) as e:
                return _error(str(e))

    @mcp.tool()
    async def hanno_complete_run(run_id: str) -> str:
        """Mark a running run as successfully completed.

        Args:
            run_id: The run ID (ULID).
        """
        async with open_ledger() as ledger:
            try:
                run = await ledger.complete_run(run_id, actor=ACTOR)
                return run.model_dump_json()
            except (LedgerError, InvalidTransitionError) as e:
                return _error(str(e))

    @mcp.tool()
    async def hanno_fail_run(run_id: str, error: str = "") -> str:
        """Mark a run as failed.

        Args:
            run_id: The run ID (ULID).
            error: Optional error message describing the failure.
        """
        async with open_ledger() as ledger:
            try:
                run = await ledger.fail_run(run_id, actor=ACTOR, error=error)
                return run.model_dump_json()
            except (LedgerError, InvalidTransitionError) as e:
                return _error(str(e))

    @mcp.tool()
    async def hanno_cancel_run(run_id: str, reason: str = "") -> str:
        """Cancel a run.

        Args:
            run_id: The run ID (ULID).
            reason: Optional reason for cancellation.
        """
        async with open_ledger() as ledger:
            try:
                run = await ledger.cancel_run(run_id, actor=ACTOR, reason=reason)
                return run.model_dump_json()
            except (LedgerError, InvalidTransitionError) as e:
                return _error(str(e))


def _error(message: str) -> str:
    """Return a JSON error response."""
    import json

    return json.dumps({"error": message})
