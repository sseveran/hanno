"""Rich output formatting for CLI commands."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.tree import Tree

console = Console()
err_console = Console(stderr=True)

STATUS_COLORS: dict[str, str] = {
    "planned": "dim",
    "queued": "dim",
    "running": "blue",
    "waiting_human": "yellow",
    "waiting": "yellow",
    "blocked": "red",
    "succeeded": "green",
    "failed": "red",
    "canceled": "dim red",
    "skipped": "dim",
    "pending": "yellow",
    "granted": "green",
    "denied": "red",
}


def styled_status(status: str) -> str:
    color = STATUS_COLORS.get(status, "white")
    return f"[{color}]{status}[/{color}]"


def print_json_or_table(
    data: list[dict[str, Any]] | dict[str, Any],
    *,
    as_json: bool = False,
) -> None:
    if as_json:
        console.print_json(json.dumps(data, default=str))
        return

    if isinstance(data, dict):
        for key, val in data.items():
            console.print(f"[bold]{key}:[/bold] {val}")
        return

    if not data:
        console.print("[dim]No results.[/dim]")
        return

    table = Table()
    for col in data[0]:
        table.add_column(col)
    for row in data:
        table.add_row(*[str(v) for v in row.values()])
    console.print(table)


def print_run(run: dict[str, Any], *, as_json: bool = False) -> None:
    if as_json:
        console.print_json(json.dumps(run, default=str))
        return
    console.print(f"[bold]Run {run['id']}[/bold]")
    console.print(f"  Type:    {run['run_type']}")
    console.print(f"  Status:  {styled_status(run['status'])}")
    if run.get("title"):
        console.print(f"  Title:   {run['title']}")
    if run.get("labels"):
        console.print(f"  Labels:  {run['labels']}")
    if run.get("external_refs"):
        for ref in run["external_refs"]:
            url_part = f" ({ref['url']})" if ref.get("url") else ""
            ref_str = f"{ref['system']}:{ref['ref_type']}:{ref['ref_id']}"
            console.print(f"  Ref:     {ref_str}{url_part}")
    console.print(f"  Created: {run['created_at']}")
    console.print(f"  Updated: {run['updated_at']}")


def print_runs_table(
    runs: list[dict[str, Any]], *, as_json: bool = False
) -> None:
    if as_json:
        console.print_json(json.dumps(runs, default=str))
        return
    if not runs:
        console.print("[dim]No runs found.[/dim]")
        return
    table = Table(title="Runs")
    table.add_column("ID", style="bold")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Title", max_width=30)
    table.add_column("Created")
    for r in runs:
        table.add_row(
            r["id"],
            r["run_type"],
            styled_status(r["status"]),
            r.get("title", ""),
            str(r["created_at"])[:19],
        )
    console.print(table)


def print_steps_table(
    steps: list[dict[str, Any]], *, as_json: bool = False
) -> None:
    if as_json:
        console.print_json(json.dumps(steps, default=str))
        return
    if not steps:
        console.print("[dim]No steps found.[/dim]")
        return
    table = Table(title="Steps")
    table.add_column("ID", style="bold")
    table.add_column("Name")
    table.add_column("Status")
    table.add_column("Iter")
    table.add_column("Summary", max_width=30)
    for s in steps:
        table.add_row(
            s["id"],
            s["step_name"],
            styled_status(s["status"]),
            str(s.get("iteration", 0)),
            s.get("summary", ""),
        )
    console.print(table)


def print_events_table(
    events: list[dict[str, Any]], *, as_json: bool = False
) -> None:
    if as_json:
        console.print_json(json.dumps(events, default=str))
        return
    if not events:
        console.print("[dim]No events found.[/dim]")
        return
    table = Table(title="Events")
    table.add_column("Seq", justify="right")
    table.add_column("Kind")
    table.add_column("Actor")
    table.add_column("Time")
    for e in events:
        actor = e.get("actor", {})
        actor_str = f"{actor.get('provider', '?')}:{actor.get('identifier', '?')}"
        table.add_row(
            str(e["sequence"]),
            e["kind"],
            actor_str,
            str(e["timestamp"])[:19],
        )
    console.print(table)


def print_search_results(
    results: list[object], *, as_json: bool = False
) -> None:
    from hanno_core.models.search import SearchResult

    typed: list[SearchResult] = [
        r if isinstance(r, SearchResult) else SearchResult.model_validate(r)
        for r in results
    ]
    if as_json:
        console.print_json(json.dumps([r.model_dump() for r in typed], default=str))
        return
    if not typed:
        console.print("[dim]No results found.[/dim]")
        return
    table = Table(title="Search Results")
    table.add_column("Score", justify="right", style="bold")
    table.add_column("Type")
    table.add_column("ID")
    table.add_column("Run")
    table.add_column("Snippet", max_width=50)
    for r in typed:
        snippet = escape(r.snippet).replace("<b>", "[bold]").replace("</b>", "[/bold]")
        table.add_row(
            f"{r.score:.2f}",
            r.entity_type.value,
            r.entity_id,
            r.run_id,
            snippet,
        )
    console.print(table)


def print_step_tree(
    steps: list[dict[str, Any]], *, as_json: bool = False
) -> None:
    if as_json:
        console.print_json(json.dumps(steps, default=str))
        return
    if not steps:
        console.print("[dim]No steps.[/dim]")
        return
    tree = Tree("[bold]Steps[/bold]")
    for s in steps:
        label = (
            f"{s['step_name']} [{styled_status(s['status'])}]"
            f" (iter={s.get('iteration', 0)})"
        )
        if s.get("summary"):
            label += f" — {s['summary']}"
        tree.add(label)
    console.print(tree)
