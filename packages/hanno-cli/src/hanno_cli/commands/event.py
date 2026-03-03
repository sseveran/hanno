"""Event commands."""

from __future__ import annotations

from typing import Annotated

import typer
from hanno_core.models.identity import ActorRef

from hanno_cli.config import async_command, open_ledger
from hanno_cli.formatting import console, print_events_table

app = typer.Typer(name="event", help="View ledger events")

JsonOpt = Annotated[bool, typer.Option("--json", help="Output as JSON")]


def _actor() -> ActorRef:
    return ActorRef(provider="cli", identifier="local")


@app.command("list")
@async_command
async def list_events(
    run_id: Annotated[str, typer.Argument(help="Run ID")],
    after: Annotated[int, typer.Option(help="After sequence number")] = 0,
    limit: Annotated[int, typer.Option(help="Max results")] = 100,
    json_output: JsonOpt = False,
) -> None:
    """List events for a run."""
    async with open_ledger() as ledger:
        events = await ledger.list_events(
            run_id, after_sequence=after, limit=limit
        )
    print_events_table(
        [e.model_dump() for e in events], as_json=json_output
    )


@app.command()
@async_command
async def note(
    run_id: Annotated[str, typer.Argument(help="Run ID")],
    message: Annotated[str, typer.Argument(help="Note message")],
    json_output: JsonOpt = False,
) -> None:
    """Add a note event to a run."""
    async with open_ledger() as ledger:
        event = await ledger.add_note(
            run_id, actor=_actor(), message=message
        )
    if json_output:
        console.print_json(event.model_dump_json())
    else:
        console.print(f"Note added (seq={event.sequence})")
