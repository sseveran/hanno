"""Workspace management commands."""

from __future__ import annotations

import json
from typing import Annotated

import typer
from hanno_core.models import ExternalRef, WorkspaceStatus

from hanno_cli.config import async_command, open_ledger
from hanno_cli.formatting import console, err_console, print_json_or_table

app = typer.Typer(name="workspace", help="Manage workspaces and attached repos")
repo_app = typer.Typer(name="repo", help="Manage repos attached to a workspace")
app.add_typer(repo_app, name="repo")

JsonOpt = Annotated[bool, typer.Option("--json", help="Output as JSON")]


def _parse_refs(items: list[str] | None) -> list[ExternalRef]:
    refs: list[ExternalRef] = []
    for item in items or []:
        parts = item.split(":", 3)
        if len(parts) < 3:  # noqa: PLR2004
            err_console.print(
                f"[red]Invalid ref format: {item} (expected system:type:id[:url])[/red]"
            )
            raise typer.Exit(1)
        refs.append(
            ExternalRef(
                system=parts[0],
                ref_type=parts[1],
                ref_id=parts[2],
                url=parts[3] if len(parts) > 3 else None,
            )
        )
    return refs


def _parse_labels(items: list[str] | None) -> dict[str, str]:
    labels: dict[str, str] = {}
    for item in items or []:
        key, _, value = item.partition("=")
        labels[key] = value
    return labels


@app.command()
@async_command
async def create(
    title: Annotated[str, typer.Option(help="Human-readable title")] = "",
    label: Annotated[
        list[str] | None, typer.Option("--label", "-l", help="Label as key=value")
    ] = None,
    ref: Annotated[
        list[str] | None, typer.Option("--ref", help="External ref as system:type:id[:url]")
    ] = None,
    json_output: JsonOpt = False,
) -> None:
    """Create a workspace."""
    async with open_ledger() as ledger:
        workspace = await ledger.create_workspace(
            title=title,
            labels=_parse_labels(label),
            external_refs=_parse_refs(ref),
        )

    if json_output:
        console.print_json(workspace.model_dump_json())
    else:
        console.print(f"Workspace [bold]{workspace.id}[/bold] created")


@app.command("list")
@async_command
async def list_workspaces(
    status: Annotated[str | None, typer.Option(help="Filter by status")] = None,
    limit: Annotated[int, typer.Option(help="Max results")] = 20,
    json_output: JsonOpt = False,
) -> None:
    """List workspaces."""
    kwargs: dict[str, object] = {"limit": limit}
    if status is not None:
        kwargs["status"] = WorkspaceStatus(status)

    async with open_ledger() as ledger:
        workspaces = await ledger.list_workspaces(**kwargs)

    data = [w.model_dump(mode="json") for w in workspaces]
    if json_output:
        console.print_json(json.dumps(data, default=str))
        return
    print_json_or_table(
        [
            {"id": w["id"], "status": w["status"], "title": w["title"]}
            for w in data
        ],
        as_json=False,
    )


@app.command()
@async_command
async def show(
    workspace_id: Annotated[str, typer.Argument(help="Workspace ID")],
    json_output: JsonOpt = False,
) -> None:
    """Show a workspace, its repos, and its tasks."""
    async with open_ledger() as ledger:
        workspace = await ledger.get_workspace(workspace_id)
        if workspace is None:
            err_console.print(f"[red]Workspace not found: {workspace_id}[/red]")
            raise typer.Exit(1)
        repos = await ledger.list_workspace_repos(workspace_id)
        tasks = await ledger.list_tasks(workspace_id=workspace_id)
        runs = await ledger.list_runs(workspace_id=workspace_id)

    if json_output:
        result = {
            "workspace": workspace.model_dump(mode="json"),
            "repos": [r.model_dump(mode="json") for r in repos],
            "tasks": [t.model_dump(mode="json") for t in tasks],
            "runs": [r.model_dump(mode="json") for r in runs],
        }
        console.print_json(json.dumps(result, default=str))
        return

    console.print(f"[bold]Workspace {workspace.id}[/bold]")
    console.print(f"  Status: {workspace.status.value}")
    if workspace.title:
        console.print(f"  Title:  {workspace.title}")
    if workspace.labels:
        console.print(f"  Labels: {workspace.labels}")
    console.print(f"  Repos:  {len(repos)}")
    console.print(f"  Tasks:  {len(tasks)}")
    console.print(f"  Runs:   {len(runs)}")


@app.command()
@async_command
async def archive(
    workspace_id: Annotated[str, typer.Argument(help="Workspace ID")],
    json_output: JsonOpt = False,
) -> None:
    """Archive a workspace."""
    async with open_ledger() as ledger:
        workspace = await ledger.archive_workspace(workspace_id)
    if json_output:
        console.print_json(workspace.model_dump_json())
    else:
        console.print(f"Workspace [bold]{workspace.id}[/bold] archived")


@repo_app.command("add")
@async_command
async def add_repo(
    workspace_id: Annotated[str, typer.Argument(help="Workspace ID")],
    canonical_remote: Annotated[
        str, typer.Option("--canonical-remote", help="Normalized repo remote")
    ] = "",
    local_path: Annotated[
        str | None, typer.Option("--local-path", help="Local checkout path")
    ] = None,
    display_name: Annotated[
        str, typer.Option("--name", help="Display name")
    ] = "",
    default_branch: Annotated[
        str | None, typer.Option("--default-branch", help="Default branch")
    ] = None,
    json_output: JsonOpt = False,
) -> None:
    """Attach a repo to a workspace."""
    async with open_ledger() as ledger:
        repo = await ledger.create_workspace_repo(
            workspace_id,
            display_name=display_name,
            canonical_remote=canonical_remote,
            local_path=local_path,
            default_branch=default_branch,
        )
    if json_output:
        console.print_json(repo.model_dump_json())
    else:
        console.print(
            f"Repo [bold]{repo.id}[/bold] attached to "
            f"workspace [bold]{workspace_id}[/bold]"
        )


@repo_app.command("list")
@async_command
async def list_repos(
    workspace_id: Annotated[str, typer.Argument(help="Workspace ID")],
    json_output: JsonOpt = False,
) -> None:
    """List repos attached to a workspace."""
    async with open_ledger() as ledger:
        repos = await ledger.list_workspace_repos(workspace_id)

    data = [r.model_dump(mode="json") for r in repos]
    if json_output:
        console.print_json(json.dumps(data, default=str))
        return
    print_json_or_table(
        [
            {
                "id": r["id"],
                "name": r["display_name"],
                "remote": r["canonical_remote"],
                "local_path": r["local_path"] or "",
            }
            for r in data
        ],
        as_json=False,
    )
