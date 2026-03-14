"""MCP tools for task operations."""

from __future__ import annotations

from hanno_core.engine.ledger import InvalidTransitionError, LedgerError
from hanno_core.models import ExternalRef
from mcp.server.fastmcp import FastMCP

from hanno_mcp.config import open_ledger


def register(mcp: FastMCP) -> None:
    """Register task tools on the MCP server."""

    @mcp.tool()
    async def hanno_create_task(
        workspace_id: str,
        title: str = "",
        labels: dict[str, str] | None = None,
        external_refs: list[dict[str, str]] | None = None,
        workspace_repo_ids: list[str] | None = None,
    ) -> str:
        refs = [ExternalRef(**r) for r in external_refs] if external_refs else None
        async with open_ledger() as ledger:
            try:
                task = await ledger.create_task(
                    workspace_id,
                    title=title,
                    labels=labels,
                    external_refs=refs,
                    workspace_repo_ids=workspace_repo_ids,
                )
                return task.model_dump_json()
            except LedgerError as e:
                return _error(str(e))

    @mcp.tool()
    async def hanno_get_task(task_id: str) -> str:
        async with open_ledger() as ledger:
            task = await ledger.get_task(task_id)
            if task is None:
                return _error(f"Task not found: {task_id}")
            return task.model_dump_json()

    @mcp.tool()
    async def hanno_list_tasks(
        workspace_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> str:
        from hanno_core.models import TaskStatus

        async with open_ledger() as ledger:
            kwargs: dict[str, object] = {"limit": limit}
            if workspace_id is not None:
                kwargs["workspace_id"] = workspace_id
            if status is not None:
                try:
                    kwargs["status"] = TaskStatus(status)
                except ValueError:
                    return _error(f"Invalid status: {status}")
            tasks = await ledger.list_tasks(**kwargs)
            return "[" + ",".join(t.model_dump_json() for t in tasks) + "]"

    @mcp.tool()
    async def hanno_close_task(task_id: str) -> str:
        async with open_ledger() as ledger:
            try:
                task = await ledger.close_task(task_id)
                return task.model_dump_json()
            except (LedgerError, InvalidTransitionError) as e:
                return _error(str(e))

    @mcp.tool()
    async def hanno_find_tasks_by_ref(
        workspace_id: str,
        system: str,
        ref_type: str,
        ref_id: str,
    ) -> str:
        async with open_ledger() as ledger:
            tasks = await ledger.find_tasks_by_external_ref(
                workspace_id=workspace_id,
                system=system,
                ref_type=ref_type,
                ref_id=ref_id,
            )
            return "[" + ",".join(t.model_dump_json() for t in tasks) + "]"

    @mcp.tool()
    async def hanno_list_task_runs(
        task_id: str,
        status: str | None = None,
        limit: int = 50,
    ) -> str:
        from hanno_core.models import RunStatus

        async with open_ledger() as ledger:
            kwargs: dict[str, object] = {"limit": limit}
            if status is not None:
                try:
                    kwargs["status"] = RunStatus(status)
                except ValueError:
                    return _error(f"Invalid status: {status}")
            runs = await ledger.list_task_runs(task_id, **kwargs)
            return "[" + ",".join(r.model_dump_json() for r in runs) + "]"

    @mcp.tool()
    async def hanno_list_task_repos(task_id: str) -> str:
        async with open_ledger() as ledger:
            try:
                repos = await ledger.list_task_repos(task_id)
                return "[" + ",".join(r.model_dump_json() for r in repos) + "]"
            except LedgerError as e:
                return _error(str(e))


def _error(message: str) -> str:
    import json

    return json.dumps({"error": message})
