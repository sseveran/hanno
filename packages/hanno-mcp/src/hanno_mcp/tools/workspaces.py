"""MCP tools for workspace operations."""

from __future__ import annotations

from hanno_core.engine.ledger import InvalidTransitionError, LedgerError
from hanno_core.models import ExternalRef
from mcp.server.fastmcp import FastMCP

from hanno_mcp.config import open_ledger


def register(mcp: FastMCP) -> None:
    """Register workspace tools on the MCP server."""

    @mcp.tool()
    async def hanno_create_workspace(
        title: str = "",
        labels: dict[str, str] | None = None,
        external_refs: list[dict[str, str]] | None = None,
    ) -> str:
        refs = [ExternalRef(**r) for r in external_refs] if external_refs else None
        async with open_ledger() as ledger:
            try:
                workspace = await ledger.create_workspace(
                    title=title,
                    labels=labels,
                    external_refs=refs,
                )
                return workspace.model_dump_json()
            except LedgerError as e:
                return _error(str(e))

    @mcp.tool()
    async def hanno_get_workspace(workspace_id: str) -> str:
        async with open_ledger() as ledger:
            workspace = await ledger.get_workspace(workspace_id)
            if workspace is None:
                return _error(f"Workspace not found: {workspace_id}")
            return workspace.model_dump_json()

    @mcp.tool()
    async def hanno_list_workspaces(
        status: str | None = None,
        limit: int = 50,
    ) -> str:
        from hanno_core.models import WorkspaceStatus

        async with open_ledger() as ledger:
            kwargs: dict[str, object] = {"limit": limit}
            if status is not None:
                try:
                    kwargs["status"] = WorkspaceStatus(status)
                except ValueError:
                    return _error(f"Invalid status: {status}")
            workspaces = await ledger.list_workspaces(**kwargs)
            return "[" + ",".join(w.model_dump_json() for w in workspaces) + "]"

    @mcp.tool()
    async def hanno_archive_workspace(workspace_id: str) -> str:
        async with open_ledger() as ledger:
            try:
                workspace = await ledger.archive_workspace(workspace_id)
                return workspace.model_dump_json()
            except (LedgerError, InvalidTransitionError) as e:
                return _error(str(e))

    @mcp.tool()
    async def hanno_create_workspace_repo(
        workspace_id: str,
        display_name: str = "",
        canonical_remote: str = "",
        local_path: str | None = None,
        default_branch: str | None = None,
    ) -> str:
        async with open_ledger() as ledger:
            try:
                repo = await ledger.create_workspace_repo(
                    workspace_id,
                    display_name=display_name,
                    canonical_remote=canonical_remote,
                    local_path=local_path,
                    default_branch=default_branch,
                )
                return repo.model_dump_json()
            except LedgerError as e:
                return _error(str(e))

    @mcp.tool()
    async def hanno_list_workspace_repos(workspace_id: str) -> str:
        async with open_ledger() as ledger:
            try:
                repos = await ledger.list_workspace_repos(workspace_id)
                return "[" + ",".join(r.model_dump_json() for r in repos) + "]"
            except LedgerError as e:
                return _error(str(e))


def _error(message: str) -> str:
    import json

    return json.dumps({"error": message})
