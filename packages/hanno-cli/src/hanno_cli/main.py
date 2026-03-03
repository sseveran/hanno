"""Hanno CLI entry point."""

import typer

from hanno_cli.commands import approval, artifact, event, run, step

app = typer.Typer(name="hanno", help="Workflow Ledger CLI")

app.add_typer(run.app, name="run")
app.add_typer(step.app, name="step")
app.add_typer(event.app, name="event")
app.add_typer(artifact.app, name="artifact")
app.add_typer(approval.app, name="approval")


if __name__ == "__main__":
    app()
