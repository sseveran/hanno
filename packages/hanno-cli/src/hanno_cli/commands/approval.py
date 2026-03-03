"""Approval commands."""

from __future__ import annotations

import json
from typing import Annotated

import typer
from hanno_core.models import ApprovalStatus
from hanno_core.models.identity import ActorRef

from hanno_cli.config import async_command, open_ledger
from hanno_cli.formatting import console, styled_status

app = typer.Typer(name="approval", help="Manage approvals")

JsonOpt = Annotated[bool, typer.Option("--json", help="Output as JSON")]


def _actor() -> ActorRef:
    return ActorRef(provider="cli", identifier="local")


@app.command()
@async_command
async def request(
    run_id: Annotated[str, typer.Argument(help="Run ID")],
    authority: Annotated[str, typer.Option(help="Approval authority")] = "",
    resource: Annotated[str, typer.Option(help="Resource being approved")] = "",
    json_output: JsonOpt = False,
) -> None:
    """Request an approval."""
    async with open_ledger() as ledger:
        approval = await ledger.request_approval(
            run_id,
            actor=_actor(),
            authority=authority,
            resource=resource,
        )
    if json_output:
        console.print_json(approval.model_dump_json())
    else:
        console.print(f"Approval [bold]{approval.id}[/bold] requested")


@app.command()
@async_command
async def grant(
    approval_id: Annotated[str, typer.Argument(help="Approval ID")],
    json_output: JsonOpt = False,
) -> None:
    """Grant an approval."""
    async with open_ledger() as ledger:
        approval = await ledger.grant_approval(approval_id, actor=_actor())
    if json_output:
        console.print_json(approval.model_dump_json())
    else:
        console.print(f"Approval [bold]{approval.id}[/bold] granted")


@app.command()
@async_command
async def deny(
    approval_id: Annotated[str, typer.Argument(help="Approval ID")],
    reason: Annotated[str, typer.Option(help="Denial reason")] = "",
    json_output: JsonOpt = False,
) -> None:
    """Deny an approval."""
    async with open_ledger() as ledger:
        approval = await ledger.deny_approval(
            approval_id, actor=_actor(), reason=reason
        )
    if json_output:
        console.print_json(approval.model_dump_json())
    else:
        console.print(f"Approval [bold]{approval.id}[/bold] denied")


@app.command("list")
@async_command
async def list_approvals(
    run_id: Annotated[str, typer.Argument(help="Run ID")],
    pending: Annotated[bool, typer.Option(help="Only pending")] = False,
    json_output: JsonOpt = False,
) -> None:
    """List approvals for a run."""
    async with open_ledger() as ledger:
        status = ApprovalStatus.PENDING if pending else None
        approvals = await ledger.list_approvals(run_id, status=status)
    if json_output:
        console.print_json(
            json.dumps([a.model_dump() for a in approvals], default=str)
        )
    else:
        if not approvals:
            console.print("[dim]No approvals found.[/dim]")
            return
        from rich.table import Table

        table = Table(title="Approvals")
        table.add_column("ID", style="bold", max_width=14)
        table.add_column("Status")
        table.add_column("Authority")
        table.add_column("Resource", max_width=30)
        for a in approvals:
            table.add_row(
                a.id[:12] + "...",
                styled_status(a.status.value),
                a.authority,
                a.resource,
            )
        console.print(table)
