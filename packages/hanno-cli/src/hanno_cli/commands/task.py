"""Task management and hook lifecycle commands."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Annotated, Any, cast

import typer
from hanno_core.models import ExternalRef, Run, TaskStatus
from hanno_core.models.identity import ActorRef
from hanno_core.repo_context import derive_repo_display_name, normalize_git_remote

from hanno_cli.config import async_command, get_db_path, open_ledger
from hanno_cli.formatting import console, err_console

logger = logging.getLogger("hanno.task")

app = typer.Typer(name="task", help="Manage tasks and hook-driven task runs")

STATE_FILENAME = "active_task.json"
DEFAULT_LOG_TOOLS = {"Bash", "Write", "Edit", "NotebookEdit"}


def _setup_debug_logging() -> None:
    if os.environ.get("HANNO_DEBUG"):
        logging.basicConfig(
            level=logging.DEBUG,
            format="[hanno:%(levelname)s] %(message)s",
            stream=sys.stderr,
        )
    else:
        logging.basicConfig(level=logging.WARNING, stream=sys.stderr)


def _actor() -> ActorRef:
    return ActorRef(provider="cli", identifier="hook")


def _state_path() -> Path:
    return get_db_path().parent / STATE_FILENAME


def _read_state() -> dict[str, Any] | None:
    path = _state_path()
    if not path.exists():
        return None
    return cast(dict[str, Any], json.loads(path.read_text()))


def _write_state(state: dict[str, Any]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, default=str))


def _clear_state() -> None:
    path = _state_path()
    if path.exists():
        path.unlink()


def _read_hook_input() -> dict[str, Any]:
    if not sys.stdin.isatty():
        try:
            data = sys.stdin.read()
            if data.strip():
                return cast(dict[str, Any], json.loads(data))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _parse_ref(ref_str: str) -> ExternalRef | None:
    parts = ref_str.split(":", 3)
    if len(parts) < 3:  # noqa: PLR2004
        return None
    return ExternalRef(
        system=parts[0],
        ref_type=parts[1],
        ref_id=parts[2],
        url=parts[3] if len(parts) > 3 else None,
    )


def _parse_refs(items: list[str] | None) -> list[ExternalRef]:
    refs: list[ExternalRef] = []
    for item in items or []:
        ref = _parse_ref(item)
        if ref is None:
            err_console.print(
                f"[red]Invalid ref format: {item} (expected system:type:id[:url])[/red]"
            )
            raise typer.Exit(1)
        refs.append(ref)
    return refs


def _parse_labels(items: list[str] | None) -> dict[str, str]:
    labels: dict[str, str] = {}
    for item in items or []:
        key, _, value = item.partition("=")
        labels[key] = value
    return labels


def _context_message(
    run: Run,
    step_id: str,
    *,
    action: str,
    workspace_id: str,
    task_id: str | None,
) -> str:
    title_part = f' "{run.title}"' if run.title else ""
    task_part = f" task={task_id}" if task_id else ""
    return (
        f"[Hanno] {action} run {run.id}"
        f" (type: {run.run_type}{title_part}, workspace={workspace_id}{task_part})."
        f" Step {step_id} active."
    )


def _run_git(args: list[str], cwd: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", cwd, *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    output = result.stdout.strip()
    return output or None


def _resolve_repo_context(cwd: str | None) -> dict[str, str] | None:
    if not cwd:
        return None
    git_root = _run_git(["rev-parse", "--show-toplevel"], cwd)
    if git_root is None:
        return None
    remote = _run_git(["remote", "get-url", "origin"], git_root)
    canonical_remote = normalize_git_remote(remote)
    return {
        "git_root": git_root,
        "remote_url": remote or "",
        "canonical_remote": canonical_remote,
        "display_name": derive_repo_display_name(canonical_remote, git_root),
    }


async def _close_previous_task_run(hook_input: dict[str, Any], *, source: str) -> None:
    prev_state = _read_state()
    if prev_state is None:
        return

    actor = _actor()
    transcript_path = hook_input.get("transcript_path")
    try:
        async with open_ledger() as ledger:
            if transcript_path:
                path = Path(transcript_path)
                if path.exists():
                    data = path.read_bytes()
                    await ledger.attach_artifact(
                        prev_state["run_id"],
                        data=data,
                        kind="transcript",
                        actor=actor,
                        name=f"transcript-{source}-{prev_state['step_run_id'][:12]}.json",
                        content_type="application/json",
                        step_run_id=prev_state["step_run_id"],
                    )
            await ledger.complete_step(
                prev_state["step_run_id"],
                actor=actor,
                summary=f"Task step closed (transition: {source})",
            )
    except Exception:
        logger.exception(
            "Failed to close previous task run (step %s)",
            prev_state["step_run_id"],
        )
    _clear_state()


async def _resolve_workspace_and_repo(
    ledger,
    *,
    repo_context: dict[str, str] | None,
    task_hint_present: bool,
):
    workspace_id_env = os.environ.get("HANNO_WORKSPACE_ID")
    if workspace_id_env:
        workspace = await ledger.get_workspace(workspace_id_env)
        if workspace is None:
            err_console.print(f"[red]Workspace not found: {workspace_id_env}[/red]")
            raise typer.Exit(1)

        workspace_repo = None
        if repo_context is not None:
            matches = await _find_workspace_repo_match(ledger, workspace.id, repo_context)
            if len(matches) == 1:
                workspace_repo = matches[0]
        return workspace, workspace_repo

    if repo_context is None:
        err_console.print(
            "[red]Workspace could not be inferred. "
            "Set HANNO_WORKSPACE_ID or run from a git repo.[/red]"
        )
        raise typer.Exit(1)

    matches = []
    if repo_context["canonical_remote"]:
        matches = await ledger.find_workspace_repos(
            canonical_remote=repo_context["canonical_remote"]
        )
    if not matches:
        matches = await ledger.find_workspace_repos(local_path=repo_context["git_root"])

    workspace_ids = {repo.workspace_id for repo in matches}
    if len(workspace_ids) > 1:
        err_console.print(
            "[red]Multiple workspaces match this repo context. Set HANNO_WORKSPACE_ID.[/red]"
        )
        raise typer.Exit(1)
    if len(workspace_ids) == 1:
        workspace = await ledger.get_workspace(next(iter(workspace_ids)))
        if workspace is None:
            err_console.print("[red]Matched workspace could not be loaded.[/red]")
            raise typer.Exit(1)
        workspace_repo = next(
            (
                repo
                for repo in matches
                if repo.local_path == repo_context["git_root"]
            ),
            matches[0],
        )
        return workspace, workspace_repo

    if not task_hint_present:
        err_console.print(
            "[red]No workspace matches this repo and no task hint was provided. "
            "Set HANNO_TASK_ID or HANNO_TASK_REF.[/red]"
        )
        raise typer.Exit(1)

    workspace = await ledger.create_workspace(title=repo_context["display_name"])
    workspace_repo = await ledger.create_workspace_repo(
        workspace.id,
        display_name=repo_context["display_name"],
        canonical_remote=repo_context["canonical_remote"],
        local_path=repo_context["git_root"],
    )
    return workspace, workspace_repo


async def _find_workspace_repo_match(
    ledger,
    workspace_id: str,
    repo_context: dict[str, str],
) -> list:
    matches = []
    if repo_context["canonical_remote"]:
        matches = await ledger.find_workspace_repos(
            workspace_id=workspace_id,
            canonical_remote=repo_context["canonical_remote"],
        )
    if not matches:
        matches = await ledger.find_workspace_repos(
            workspace_id=workspace_id,
            local_path=repo_context["git_root"],
        )
    return matches


async def _resolve_task(
    ledger,
    *,
    workspace_id: str,
    workspace_repo_id: str | None,
):
    task_id_env = os.environ.get("HANNO_TASK_ID")
    task_ref_env = os.environ.get("HANNO_TASK_REF")

    if task_id_env:
        task = await ledger.get_task(task_id_env)
        if task is None:
            err_console.print(f"[red]Task not found: {task_id_env}[/red]")
            raise typer.Exit(1)
        if task.workspace_id != workspace_id:
            err_console.print("[red]Task does not belong to the resolved workspace.[/red]")
            raise typer.Exit(1)
        return task

    if task_ref_env:
        ref = _parse_ref(task_ref_env)
        if ref is None:
            err_console.print(
                "[red]Invalid HANNO_TASK_REF: "
                f"{task_ref_env} (expected system:type:id[:url])[/red]"
            )
            raise typer.Exit(1)
        tasks = await ledger.find_tasks_by_external_ref(
            workspace_id=workspace_id,
            system=ref.system,
            ref_type=ref.ref_type,
            ref_id=ref.ref_id,
            status=TaskStatus.ACTIVE,
        )
        if tasks:
            task = tasks[0]
        else:
            task = await ledger.create_task(
                workspace_id,
                title=ref.ref_id,
                external_refs=[ref],
                workspace_repo_ids=[workspace_repo_id] if workspace_repo_id else None,
            )
        if workspace_repo_id is not None:
            await ledger.link_task_repo(task.id, workspace_repo_id)
        return task

    err_console.print(
        "[red]No task hint available. Set HANNO_TASK_ID or HANNO_TASK_REF.[/red]"
    )
    raise typer.Exit(1)


@app.command()
@async_command
async def create(
    workspace_id: Annotated[str, typer.Option("--workspace-id", help="Workspace ID")],
    title: Annotated[str, typer.Option(help="Task title")] = "",
    repo_id: Annotated[
        list[str] | None,
        typer.Option("--repo-id", help="Workspace repo ID to attach"),
    ] = None,
    label: Annotated[
        list[str] | None,
        typer.Option("--label", "-l", help="Label as key=value"),
    ] = None,
    ref: Annotated[
        list[str] | None,
        typer.Option("--ref", help="External ref as system:type:id[:url]"),
    ] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Create a task."""
    async with open_ledger() as ledger:
        task = await ledger.create_task(
            workspace_id,
            title=title,
            workspace_repo_ids=repo_id,
            labels=_parse_labels(label),
            external_refs=_parse_refs(ref),
        )
    if json_output:
        console.print_json(task.model_dump_json())
    else:
        console.print(f"Task [bold]{task.id}[/bold] created")


@app.command("list")
@async_command
async def list_tasks(
    workspace_id: Annotated[
        str | None, typer.Option("--workspace-id", help="Filter by workspace")
    ] = None,
    status: Annotated[
        str | None, typer.Option(help="Filter by status (active, closed, archived)")
    ] = None,
    limit: Annotated[int, typer.Option(help="Max results")] = 20,
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """List tasks."""
    kwargs: dict[str, object] = {"limit": limit}
    if workspace_id is not None:
        kwargs["workspace_id"] = workspace_id
    if status is not None:
        kwargs["status"] = TaskStatus(status)
    async with open_ledger() as ledger:
        tasks = await ledger.list_tasks(**kwargs)

    if json_output:
        console.print_json(json.dumps([t.model_dump(mode="json") for t in tasks], default=str))
        return
    if not tasks:
        console.print("[dim]No tasks found.[/dim]")
        return
    for task in tasks:
        console.print(
            f"  {task.id}  {task.status.value:<8} "
            f"workspace={task.workspace_id}  {task.title}"
        )


@app.command()
@async_command
async def show(
    task_id: Annotated[str, typer.Argument(help="Task ID")],
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Show task details, repos, and runs."""
    async with open_ledger() as ledger:
        task = await ledger.get_task(task_id)
        if task is None:
            err_console.print(f"[red]Task not found: {task_id}[/red]")
            raise typer.Exit(1)
        repos = await ledger.list_task_repos(task_id)
        runs = await ledger.list_task_runs(task_id)

    if json_output:
        result = {
            "task": task.model_dump(mode="json"),
            "repos": [r.model_dump(mode="json") for r in repos],
            "runs": [r.model_dump(mode="json") for r in runs],
        }
        console.print_json(json.dumps(result, default=str))
        return

    console.print(f"[bold]Task {task.id}[/bold]")
    console.print(f"  Workspace: {task.workspace_id}")
    console.print(f"  Status:    {task.status.value}")
    if task.title:
        console.print(f"  Title:     {task.title}")
    console.print(f"  Repos:     {len(repos)}")
    console.print(f"  Runs:      {len(runs)}")


@app.command()
@async_command
async def close(
    task_id: Annotated[str, typer.Argument(help="Task ID")],
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Close an active task."""
    async with open_ledger() as ledger:
        task = await ledger.close_task(task_id)
    if json_output:
        console.print_json(task.model_dump_json())
    else:
        console.print(f"Task [bold]{task.id}[/bold] closed")


@app.command()
@async_command
async def archive(
    task_id: Annotated[str, typer.Argument(help="Task ID")],
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Archive a task."""
    async with open_ledger() as ledger:
        task = await ledger.archive_task(task_id)
    if json_output:
        console.print_json(task.model_dump_json())
    else:
        console.print(f"Task [bold]{task.id}[/bold] archived")


@app.command()
@async_command
async def start(
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Start or resume a hook-driven task run."""
    _setup_debug_logging()
    hook_input = _read_hook_input()
    tool_session_id = hook_input.get("session_id", "")
    source = hook_input.get("source", "startup")

    if source == "compact":
        state = _read_state()
        if state is not None:
            if json_output:
                print(json.dumps(state, default=str))  # noqa: T201
            else:
                async with open_ledger() as ledger:
                    run = await ledger.get_run(state["run_id"])
                if run is not None:
                    print(  # noqa: T201
                        _context_message(
                            run,
                            state["step_run_id"],
                            action="Resumed (post-compaction)",
                            workspace_id=state["workspace_id"],
                            task_id=state.get("task_id"),
                        )
                    )
        return

    if source == "resume":
        state = _read_state()
        if state is not None and state.get("tool_session_id") == tool_session_id:
            if json_output:
                print(json.dumps(state, default=str))  # noqa: T201
            else:
                async with open_ledger() as ledger:
                    run = await ledger.get_run(state["run_id"])
                if run is not None:
                    print(  # noqa: T201
                        _context_message(
                            run,
                            state["step_run_id"],
                            action="Resumed",
                            workspace_id=state["workspace_id"],
                            task_id=state.get("task_id"),
                        )
                    )
            return

    await _close_previous_task_run(hook_input, source=source)

    actor = _actor()
    run_type = os.environ.get("HANNO_RUN_TYPE", "claude_session")
    repo_context = _resolve_repo_context(cast(str | None, hook_input.get("cwd")))

    async with open_ledger() as ledger:
        run = None
        workspace = None
        task = None
        workspace_repo = None
        created = False

        run_id_env = os.environ.get("HANNO_RUN_ID")
        if run_id_env:
            run = await ledger.get_run(run_id_env)
            if run is None:
                err_console.print(f"[red]Run not found: {run_id_env}[/red]")
                raise typer.Exit(1)
            workspace = await ledger.get_workspace(run.workspace_id)
            if workspace is None:
                err_console.print("[red]Workspace for run not found.[/red]")
                raise typer.Exit(1)
            if run.task_id:
                task = await ledger.get_task(run.task_id)
            if run.workspace_repo_id:
                workspace_repo = await ledger.get_workspace_repo(run.workspace_repo_id)
        else:
            task_hint_present = bool(
                os.environ.get("HANNO_TASK_ID") or os.environ.get("HANNO_TASK_REF")
            )
            workspace, workspace_repo = await _resolve_workspace_and_repo(
                ledger,
                repo_context=repo_context,
                task_hint_present=task_hint_present,
            )
            task = await _resolve_task(
                ledger,
                workspace_id=workspace.id,
                workspace_repo_id=workspace_repo.id if workspace_repo else None,
            )
            if workspace_repo is None and repo_context is not None:
                matches = await _find_workspace_repo_match(ledger, workspace.id, repo_context)
                if len(matches) == 1:
                    workspace_repo = matches[0]
            if task is not None and workspace_repo is not None:
                await ledger.link_task_repo(task.id, workspace_repo.id)

            run = await ledger.create_run(
                run_type,
                actor=actor,
                workspace_id=workspace.id,
                task_id=task.id if task else None,
                workspace_repo_id=workspace_repo.id if workspace_repo else None,
            )
            created = True

        if run.status.value == "planned":
            run = await ledger.start_run(run.id, actor=actor)

        step = await ledger.add_step(
            run.id,
            step_name="task-step",
            actor=actor,
            metadata={
                "tool_session_id": tool_session_id,
                "source": source,
                "workspace_id": run.workspace_id,
                "task_id": run.task_id,
                "workspace_repo_id": run.workspace_repo_id,
                **({"cwd": hook_input["cwd"]} if hook_input.get("cwd") else {}),
            },
        )
        step = await ledger.start_step(step.id, actor=actor)

        state = {
            "workspace_id": run.workspace_id,
            "task_id": run.task_id,
            "workspace_repo_id": run.workspace_repo_id,
            "run_id": run.id,
            "step_run_id": step.id,
            "tool_session_id": tool_session_id,
        }
        _write_state(state)

    if json_output:
        print(json.dumps(state, default=str))  # noqa: T201
    else:
        print(  # noqa: T201
            _context_message(
                run,
                step.id,
                action="Created" if created else "Resumed",
                workspace_id=run.workspace_id,
                task_id=run.task_id,
            )
        )


@app.command()
@async_command
async def snapshot(
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """Snapshot transcript and rotate the active step."""
    _setup_debug_logging()
    hook_input = _read_hook_input()
    transcript_path = hook_input.get("transcript_path")
    trigger = hook_input.get("trigger", "unknown")
    state = _read_state()
    actor = _actor()

    if state is None:
        err_console.print("[dim]No active task run.[/dim]")
        raise typer.Exit(1)

    async with open_ledger() as ledger:
        if transcript_path:
            path = Path(transcript_path)
            if path.exists():
                data = path.read_bytes()
                await ledger.attach_artifact(
                    state["run_id"],
                    data=data,
                    kind="transcript",
                    actor=actor,
                    name=f"transcript-{state['step_run_id'][:12]}.json",
                    content_type="application/json",
                    step_run_id=state["step_run_id"],
                )

        await ledger.complete_step(
            state["step_run_id"],
            actor=actor,
            summary=f"Task step compacted ({trigger})",
        )

        new_step = await ledger.add_step(
            state["run_id"],
            step_name="task-step",
            actor=actor,
            depends_on=[state["step_run_id"]],
            metadata={
                "tool_session_id": state["tool_session_id"],
                "after_compaction": True,
                "trigger": trigger,
                "workspace_id": state["workspace_id"],
                "task_id": state.get("task_id"),
                "workspace_repo_id": state.get("workspace_repo_id"),
            },
        )
        new_step = await ledger.start_step(new_step.id, actor=actor)
        state["step_run_id"] = new_step.id
        _write_state(state)

    if json_output:
        print(json.dumps(state, default=str))  # noqa: T201
    else:
        print(f"[Hanno] Transcript saved. New step {new_step.id} started (post-compaction).")  # noqa: T201


@app.command()
@async_command
async def end(
    json_output: Annotated[bool, typer.Option("--json", help="Output as JSON")] = False,
) -> None:
    """End the active hook-driven task run."""
    _setup_debug_logging()
    hook_input = _read_hook_input()
    transcript_path = hook_input.get("transcript_path")
    reason = hook_input.get("reason", "unknown")
    state = _read_state()
    actor = _actor()

    if state is None:
        err_console.print("[dim]No active task run.[/dim]")
        raise typer.Exit(1)

    async with open_ledger() as ledger:
        if transcript_path:
            path = Path(transcript_path)
            if path.exists():
                data = path.read_bytes()
                await ledger.attach_artifact(
                    state["run_id"],
                    data=data,
                    kind="transcript",
                    actor=actor,
                    name=f"transcript-final-{state['step_run_id'][:12]}.json",
                    content_type="application/json",
                    step_run_id=state["step_run_id"],
                )
        await ledger.complete_step(
            state["step_run_id"],
            actor=actor,
            summary=f"Task run ended ({reason})",
        )

    _clear_state()
    if json_output:
        print(json.dumps({"ended": True, "run_id": state["run_id"]}))  # noqa: T201
    else:
        print(f"[Hanno] Task run ended. Step {state['step_run_id']} completed.")  # noqa: T201


@app.command("log-tool")
@async_command
async def log_tool() -> None:
    """Log a tool-use note from a hook payload."""
    _setup_debug_logging()
    hook_input = _read_hook_input()
    state = _read_state()
    if state is None:
        return

    tool_name = hook_input.get("tool_name")
    if tool_name not in DEFAULT_LOG_TOOLS:
        return

    message = None
    tool_input = cast(dict[str, Any], hook_input.get("tool_input", {}))
    if tool_name == "Bash":
        message = f"[tool] Bash: {tool_input.get('command', '')}"
    elif tool_name in {"Write", "Edit", "NotebookEdit"}:
        message = f"[tool] {tool_name}: {tool_input.get('file_path', '')}"

    if message is None:
        return

    async with open_ledger() as ledger:
        await ledger.add_note(
            state["run_id"],
            actor=_actor(),
            message=message,
            step_run_id=state["step_run_id"],
        )


@app.command("log-stop")
@async_command
async def log_stop() -> None:
    """Log a stop event from the hook payload."""
    _setup_debug_logging()
    hook_input = _read_hook_input()
    state = _read_state()
    if state is None:
        return

    stop_active = hook_input.get("stop_hook_active", False)
    message = "[stop] Agent finished responding"
    if stop_active:
        message += " (stop hook active)"

    async with open_ledger() as ledger:
        await ledger.add_note(
            state["run_id"],
            actor=_actor(),
            message=message,
            step_run_id=state["step_run_id"],
        )


HOOK_CONFIG = {
    "hooks": {
        "SessionStart": [{"hooks": [{"type": "command", "command": "hanno task start"}]}],
        "PreCompact": [{"hooks": [{"type": "command", "command": "hanno task snapshot"}]}],
        "PostToolUse": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "hanno task log-tool",
                        "async": True,
                    }
                ]
            }
        ],
        "Stop": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "hanno task log-stop",
                        "async": True,
                    }
                ]
            }
        ],
        "SessionEnd": [{"hooks": [{"type": "command", "command": "hanno task end"}]}],
    }
}


@app.command("hooks")
def show_hooks() -> None:
    """Print Claude Code hook configuration JSON."""
    print(json.dumps(HOOK_CONFIG, indent=2))  # noqa: T201
