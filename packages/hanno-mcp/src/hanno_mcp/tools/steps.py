"""MCP tools for step lifecycle operations."""

from __future__ import annotations

from hanno_core.engine.ledger import InvalidTransitionError, LedgerError
from hanno_core.models.identity import ActorRef
from mcp.server.fastmcp import FastMCP

from hanno_mcp.config import open_ledger

ACTOR = ActorRef(provider="mcp", identifier="agent")


def register(mcp: FastMCP) -> None:
    """Register step tools on the MCP server."""

    @mcp.tool()
    async def hanno_add_step(
        run_id: str,
        step_name: str,
        depends_on: list[str] | None = None,
        iteration: int = 0,
    ) -> str:
        """Add a step to a run.

        Args:
            run_id: The run ID (ULID).
            step_name: Name of the step (e.g. 'build', 'test', 'deploy').
            depends_on: Optional list of step_run_ids this step depends on.
            iteration: Iteration number for retried steps (default 0).
        """
        async with open_ledger() as ledger:
            try:
                step = await ledger.add_step(
                    run_id,
                    step_name=step_name,
                    actor=ACTOR,
                    depends_on=depends_on,
                    iteration=iteration,
                )
                return step.model_dump_json()
            except LedgerError as e:
                return _error(str(e))

    @mcp.tool()
    async def hanno_start_step(step_run_id: str) -> str:
        """Start a queued step, transitioning it to 'running' status.

        Args:
            step_run_id: The step run ID (ULID).
        """
        async with open_ledger() as ledger:
            try:
                step = await ledger.start_step(step_run_id, actor=ACTOR)
                return step.model_dump_json()
            except (LedgerError, InvalidTransitionError) as e:
                return _error(str(e))

    @mcp.tool()
    async def hanno_complete_step(
        step_run_id: str,
        summary: str = "",
        output: dict[str, object] | None = None,
    ) -> str:
        """Mark a running step as successfully completed.

        Args:
            step_run_id: The step run ID (ULID).
            summary: Optional summary of what the step accomplished.
            output: Optional structured output data.
        """
        async with open_ledger() as ledger:
            try:
                step = await ledger.complete_step(
                    step_run_id, actor=ACTOR, summary=summary, output=output
                )
                return step.model_dump_json()
            except (LedgerError, InvalidTransitionError) as e:
                return _error(str(e))

    @mcp.tool()
    async def hanno_fail_step(step_run_id: str, error: str = "") -> str:
        """Mark a running step as failed.

        Args:
            step_run_id: The step run ID (ULID).
            error: Optional error message describing the failure.
        """
        async with open_ledger() as ledger:
            try:
                step = await ledger.fail_step(step_run_id, actor=ACTOR, error=error)
                return step.model_dump_json()
            except (LedgerError, InvalidTransitionError) as e:
                return _error(str(e))

    @mcp.tool()
    async def hanno_list_steps(run_id: str) -> str:
        """List all steps for a run.

        Args:
            run_id: The run ID (ULID).
        """
        async with open_ledger() as ledger:
            steps = await ledger.list_steps(run_id)
            return "[" + ",".join(s.model_dump_json() for s in steps) + "]"


def _error(message: str) -> str:
    import json

    return json.dumps({"error": message})
