"""Step management commands."""

from __future__ import annotations

from typing import Annotated

import typer
from hanno_core.models.identity import ActorRef

from hanno_cli.config import async_command, open_ledger
from hanno_cli.formatting import console, print_steps_table

app = typer.Typer(name="step", help="Manage workflow steps")

JsonOpt = Annotated[bool, typer.Option("--json", help="Output as JSON")]


def _actor() -> ActorRef:
    return ActorRef(provider="cli", identifier="local")


@app.command()
@async_command
async def add(
    run_id: Annotated[str, typer.Argument(help="Run ID")],
    step_name: Annotated[str, typer.Argument(help="Step name")],
    depends_on: Annotated[
        list[str] | None,
        typer.Option("--depends-on", "-d", help="Step IDs this depends on"),
    ] = None,
    iteration: Annotated[int, typer.Option(help="Iteration number")] = 0,
    json_output: JsonOpt = False,
) -> None:
    """Add a step to a run."""
    async with open_ledger() as ledger:
        step = await ledger.add_step(
            run_id,
            step_name=step_name,
            actor=_actor(),
            iteration=iteration,
            depends_on=depends_on,
        )
    if json_output:
        console.print_json(step.model_dump_json())
    else:
        console.print(f"Step [bold]{step.id}[/bold] added ({step_name})")


@app.command()
@async_command
async def start(
    step_run_id: Annotated[str, typer.Argument(help="Step run ID")],
    json_output: JsonOpt = False,
) -> None:
    """Start a queued step."""
    async with open_ledger() as ledger:
        step = await ledger.start_step(step_run_id, actor=_actor())
    if json_output:
        console.print_json(step.model_dump_json())
    else:
        console.print(f"Step [bold]{step.id}[/bold] started")


@app.command("complete")
@async_command
async def complete_step(
    step_run_id: Annotated[str, typer.Argument(help="Step run ID")],
    summary: Annotated[str, typer.Option(help="Completion summary")] = "",
    json_output: JsonOpt = False,
) -> None:
    """Mark a step as succeeded."""
    async with open_ledger() as ledger:
        step = await ledger.complete_step(
            step_run_id, actor=_actor(), summary=summary
        )
    if json_output:
        console.print_json(step.model_dump_json())
    else:
        console.print(f"Step [bold]{step.id}[/bold] completed")


@app.command("fail")
@async_command
async def fail_step(
    step_run_id: Annotated[str, typer.Argument(help="Step run ID")],
    error: Annotated[str, typer.Option(help="Error message")] = "",
    json_output: JsonOpt = False,
) -> None:
    """Mark a step as failed."""
    async with open_ledger() as ledger:
        step = await ledger.fail_step(
            step_run_id, actor=_actor(), error=error
        )
    if json_output:
        console.print_json(step.model_dump_json())
    else:
        console.print(f"Step [bold]{step.id}[/bold] failed")


@app.command("list")
@async_command
async def list_steps(
    run_id: Annotated[str, typer.Argument(help="Run ID")],
    json_output: JsonOpt = False,
) -> None:
    """List steps in a run."""
    async with open_ledger() as ledger:
        steps = await ledger.list_steps(run_id)
    print_steps_table([s.model_dump() for s in steps], as_json=json_output)
