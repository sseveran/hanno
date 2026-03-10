"""Search commands."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import typer
from hanno_core.models.search import EntityType, SearchMode

from hanno_cli.config import async_command, open_ledger
from hanno_cli.formatting import console, print_search_results

app = typer.Typer(name="search", help="Search the workflow ledger")

JsonOpt = Annotated[bool, typer.Option("--json", help="Output as JSON")]


@app.command("query")
@async_command
async def query(
    query: Annotated[str, typer.Argument(help="Search query text")],
    entity_type: Annotated[
        list[str] | None,
        typer.Option("--type", "-t", help="Entity type filter (run, event, step_run, artifact)"),
    ] = None,
    run_id: Annotated[str | None, typer.Option("--run-id", help="Filter by run ID")] = None,
    run_type: Annotated[str | None, typer.Option("--run-type", help="Filter by run type")] = None,
    status: Annotated[str | None, typer.Option("--status", help="Filter by status")] = None,
    after: Annotated[str | None, typer.Option("--after", help="After date (ISO 8601)")] = None,
    before: Annotated[str | None, typer.Option("--before", help="Before date (ISO 8601)")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max results")] = 20,
    json_output: JsonOpt = False,
) -> None:
    """Search the workflow ledger using full-text search."""
    async with open_ledger() as ledger:
        if ledger.search is None:
            console.print("[red]Search is not enabled. Set HANNO_SEARCH_ENABLED=true.[/red]")
            raise typer.Exit(1)

        types = {EntityType(t) for t in entity_type} if entity_type else None
        after_dt = datetime.fromisoformat(after).replace(tzinfo=UTC) if after else None
        before_dt = datetime.fromisoformat(before).replace(tzinfo=UTC) if before else None

        results = await ledger.search.search(
            query,
            mode=SearchMode.KEYWORD,
            entity_types=types,
            run_id=run_id,
            run_type=run_type,
            status=status,
            after=after_dt,
            before=before_dt,
            limit=limit,
        )

    print_search_results(results, as_json=json_output)


@app.command()
@async_command
async def reindex(
    json_output: JsonOpt = False,
) -> None:
    """Rebuild the search index from scratch."""
    async with open_ledger() as ledger:
        if ledger.search is None:
            console.print("[red]Search is not enabled. Set HANNO_SEARCH_ENABLED=true.[/red]")
            raise typer.Exit(1)

        # Access storage via the ledger's internal storage backend
        from hanno_core.backends.sqlite.search import SqliteFtsSearchBackend

        search = ledger.search
        if not isinstance(search, SqliteFtsSearchBackend):
            console.print("[red]Reindex is only supported for the SQLite FTS5 backend.[/red]")
            raise typer.Exit(1)

        count = await search.reindex_all(ledger._storage)

    if json_output:
        import json

        console.print_json(json.dumps({"indexed": count}))
    else:
        console.print(f"Reindexed [bold]{count}[/bold] entities")
