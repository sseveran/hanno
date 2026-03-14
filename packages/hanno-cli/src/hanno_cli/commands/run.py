"""Run management commands."""

from __future__ import annotations

from typing import Annotated

import typer
from hanno_core.models import ExternalRef, RunStatus
from hanno_core.models.identity import ActorRef

from hanno_cli.config import async_command, open_ledger
from hanno_cli.formatting import (
    console,
    print_run,
    print_runs_table,
    print_step_tree,
)

app = typer.Typer(name="run", help="Manage workflow runs")

JsonOpt = Annotated[bool, typer.Option("--json", help="Output as JSON")]


def _actor() -> ActorRef:
    return ActorRef(provider="cli", identifier="local")


@app.command()
@async_command
async def create(
    run_type: Annotated[str, typer.Argument(help="Workflow type identifier")],
    workspace_id: Annotated[
        str, typer.Option("--workspace-id", help="Workspace ID")
    ],
    title: Annotated[str, typer.Option(help="Human-readable title")] = "",
    task_id: Annotated[
        str | None, typer.Option("--task-id", help="Task ID")
    ] = None,
    workspace_repo_id: Annotated[
        str | None, typer.Option("--workspace-repo-id", help="Workspace repo ID")
    ] = None,
    label: Annotated[
        list[str] | None,
        typer.Option("--label", "-l", help="Label as key=value"),
    ] = None,
    ref: Annotated[
        list[str] | None,
        typer.Option("--ref", help="External ref as system:type:id[:url]"),
    ] = None,
    json_output: JsonOpt = False,
) -> None:
    """Create a new workflow run."""
    labels = {}
    for item in label or []:
        k, _, v = item.partition("=")
        labels[k] = v

    external_refs = []
    for item in ref or []:
        parts = item.split(":", 3)
        if len(parts) < 3:  # noqa: PLR2004
            console.print(f"[red]Invalid ref format: {item} (expected system:type:id[:url])[/red]")
            raise typer.Exit(1)
        external_refs.append(ExternalRef(
            system=parts[0],
            ref_type=parts[1],
            ref_id=parts[2],
            url=parts[3] if len(parts) > 3 else None,
        ))

    async with open_ledger() as ledger:
        run = await ledger.create_run(
            run_type,
            actor=_actor(),
            workspace_id=workspace_id,
            task_id=task_id,
            workspace_repo_id=workspace_repo_id,
            title=title,
            labels=labels,
            external_refs=external_refs,
        )
    if json_output:
        print_run(run.model_dump(), as_json=True)
    else:
        console.print(f"Run [bold]{run.id}[/bold] created (planned)")


@app.command("list")
@async_command
async def list_runs(
    status: Annotated[
        str | None, typer.Option(help="Filter by status")
    ] = None,
    run_type: Annotated[
        str | None, typer.Option("--type", help="Filter by type")
    ] = None,
    workspace_id: Annotated[
        str | None, typer.Option("--workspace-id", help="Filter by workspace")
    ] = None,
    task_id: Annotated[
        str | None, typer.Option("--task-id", help="Filter by task")
    ] = None,
    workspace_repo_id: Annotated[
        str | None, typer.Option("--workspace-repo-id", help="Filter by workspace repo")
    ] = None,
    limit: Annotated[int, typer.Option(help="Max results")] = 20,
    json_output: JsonOpt = False,
) -> None:
    """List workflow runs."""
    async with open_ledger() as ledger:
        kwargs: dict[str, object] = {"limit": limit}
        if status:
            kwargs["status"] = RunStatus(status)
        if run_type:
            kwargs["run_type"] = run_type
        if workspace_id:
            kwargs["workspace_id"] = workspace_id
        if task_id:
            kwargs["task_id"] = task_id
        if workspace_repo_id:
            kwargs["workspace_repo_id"] = workspace_repo_id
        runs = await ledger.list_runs(**kwargs)
    print_runs_table([r.model_dump() for r in runs], as_json=json_output)


@app.command()
@async_command
async def show(
    run_id: Annotated[str, typer.Argument(help="Run ID")],
    json_output: JsonOpt = False,
) -> None:
    """Show details of a run including steps."""
    async with open_ledger() as ledger:
        run = await ledger.get_run(run_id)
        if run is None:
            console.print(f"[red]Run not found: {run_id}[/red]")
            raise typer.Exit(1)
        steps = await ledger.list_steps(run_id)
    print_run(run.model_dump(), as_json=json_output)
    if not json_output and steps:
        console.print()
        print_step_tree([s.model_dump() for s in steps])


@app.command()
@async_command
async def start(
    run_id: Annotated[str, typer.Argument(help="Run ID")],
    json_output: JsonOpt = False,
) -> None:
    """Start a planned run."""
    async with open_ledger() as ledger:
        run = await ledger.start_run(run_id, actor=_actor())
    if json_output:
        print_run(run.model_dump(), as_json=True)
    else:
        console.print(f"Run [bold]{run.id}[/bold] started")


@app.command()
@async_command
async def complete(
    run_id: Annotated[str, typer.Argument(help="Run ID")],
    json_output: JsonOpt = False,
) -> None:
    """Mark a run as succeeded."""
    async with open_ledger() as ledger:
        run = await ledger.complete_run(run_id, actor=_actor())
    if json_output:
        print_run(run.model_dump(), as_json=True)
    else:
        console.print(f"Run [bold]{run.id}[/bold] completed")


@app.command()
@async_command
async def fail(
    run_id: Annotated[str, typer.Argument(help="Run ID")],
    error: Annotated[str, typer.Option(help="Error message")] = "",
    json_output: JsonOpt = False,
) -> None:
    """Mark a run as failed."""
    async with open_ledger() as ledger:
        run = await ledger.fail_run(run_id, actor=_actor(), error=error)
    if json_output:
        print_run(run.model_dump(), as_json=True)
    else:
        console.print(f"Run [bold]{run.id}[/bold] failed")


@app.command()
@async_command
async def cancel(
    run_id: Annotated[str, typer.Argument(help="Run ID")],
    reason: Annotated[str, typer.Option(help="Cancellation reason")] = "",
    json_output: JsonOpt = False,
) -> None:
    """Cancel a run."""
    async with open_ledger() as ledger:
        run = await ledger.cancel_run(run_id, actor=_actor(), reason=reason)
    if json_output:
        print_run(run.model_dump(), as_json=True)
    else:
        console.print(f"Run [bold]{run.id}[/bold] canceled")


@app.command()
@async_command
async def find(
    ref: Annotated[str, typer.Option("--ref", help="External ref as system:type:id")],
    json_output: JsonOpt = False,
) -> None:
    """Find runs by external reference."""
    parts = ref.split(":", 2)
    if len(parts) < 3:  # noqa: PLR2004
        console.print(f"[red]Invalid ref format: {ref} (expected system:type:id)[/red]")
        raise typer.Exit(1)

    async with open_ledger() as ledger:
        runs = await ledger.find_runs_by_external_ref(
            system=parts[0], ref_type=parts[1], ref_id=parts[2],
        )
    print_runs_table([r.model_dump() for r in runs], as_json=json_output)
