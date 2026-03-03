"""Artifact commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from hanno_core.models.identity import ActorRef

from hanno_cli.config import async_command, open_ledger
from hanno_cli.formatting import console

app = typer.Typer(name="artifact", help="Manage artifacts")

JsonOpt = Annotated[bool, typer.Option("--json", help="Output as JSON")]


def _actor() -> ActorRef:
    return ActorRef(provider="cli", identifier="local")


@app.command()
@async_command
async def attach(
    run_id: Annotated[str, typer.Argument(help="Run ID")],
    file_path: Annotated[Path, typer.Argument(help="File to attach")],
    kind: Annotated[str, typer.Option(help="Artifact kind")] = "file",
    name: Annotated[str | None, typer.Option(help="Display name")] = None,
    json_output: JsonOpt = False,
) -> None:
    """Attach a file as an artifact."""
    if not file_path.exists():
        console.print(f"[red]File not found: {file_path}[/red]")
        raise typer.Exit(1)

    data = file_path.read_bytes()
    display_name = name or file_path.name

    async with open_ledger() as ledger:
        artifact = await ledger.attach_artifact(
            run_id,
            data=data,
            kind=kind,
            actor=_actor(),
            name=display_name,
        )
    if json_output:
        console.print_json(artifact.model_dump_json())
    else:
        console.print(
            f"Artifact [bold]{artifact.id}[/bold] attached"
            f" ({display_name}, {artifact.size} bytes)"
        )


@app.command("list")
@async_command
async def list_artifacts(
    run_id: Annotated[str, typer.Argument(help="Run ID")],
    json_output: JsonOpt = False,
) -> None:
    """List artifacts for a run."""
    async with open_ledger() as ledger:
        artifacts = await ledger.list_artifacts(run_id)
    if json_output:
        console.print_json(
            json.dumps([a.model_dump() for a in artifacts], default=str)
        )
    else:
        if not artifacts:
            console.print("[dim]No artifacts found.[/dim]")
            return
        from rich.table import Table

        table = Table(title="Artifacts")
        table.add_column("ID", style="bold", max_width=14)
        table.add_column("Kind")
        table.add_column("Name")
        table.add_column("Size")
        table.add_column("Type")
        for a in artifacts:
            table.add_row(
                a.id[:12] + "...",
                a.kind,
                a.name,
                str(a.size),
                a.content_type,
            )
        console.print(table)
