"""Session lifecycle commands — used by Claude Code hooks."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, cast

import typer
from hanno_core.models import ExternalRef, Run
from hanno_core.models.identity import ActorRef

from hanno_cli.config import async_command, get_db_path, open_ledger
from hanno_cli.formatting import console, err_console

logger = logging.getLogger("hanno.session")

app = typer.Typer(
    name="session",
    help="Session lifecycle (used by Claude Code hooks)",
)

STATE_FILENAME = "active_session.json"


def _setup_debug_logging() -> None:
    """Enable debug logging if HANNO_DEBUG is set."""
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
    """Read Claude Code hook JSON from stdin (non-blocking)."""
    if not sys.stdin.isatty():
        try:
            data = sys.stdin.read()
            if data.strip():
                return cast(dict[str, Any], json.loads(data))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _parse_ref(ref_str: str) -> ExternalRef | None:
    """Parse 'system:type:id[:url]' into an ExternalRef."""
    parts = ref_str.split(":", 3)
    if len(parts) < 3:  # noqa: PLR2004
        return None
    return ExternalRef(
        system=parts[0],
        ref_type=parts[1],
        ref_id=parts[2],
        url=parts[3] if len(parts) > 3 else None,
    )


def _context_message(
    run: Run, step_id: str, *, action: str, hanno_session_id: str | None = None,
) -> str:
    """Build the context injection message for Claude Code."""
    title_part = f' "{run.title}"' if run.title else ""
    session_part = f" Session {hanno_session_id}." if hanno_session_id else ""
    return (
        f"[Hanno] {action} run {run.id}"
        f" (type: {run.run_type}{title_part})."
        f"{session_part}"
        f" Step {step_id} active."
    )


async def _close_previous_session(
    hook_input: dict[str, Any],
    *,
    source: str,
) -> None:
    """Close out a previous session's step if one is active.

    Called during startup/clear/new to ensure the old step is completed
    and the transcript is attached before we start a new session.
    """
    prev_state = _read_state()
    if prev_state is None:
        logger.debug("No previous session state found — nothing to close.")
        return

    actor = _actor()
    transcript_path = hook_input.get("transcript_path")

    logger.debug(
        "Closing previous session: run=%s step=%s (source=%s)",
        prev_state["run_id"],
        prev_state["step_run_id"],
        source,
    )

    try:
        async with open_ledger() as ledger:
            # Attach transcript if available
            if transcript_path:
                path = Path(transcript_path)
                if path.exists():
                    data = path.read_bytes()
                    logger.debug(
                        "Attaching transcript (%d bytes) from %s",
                        len(data),
                        transcript_path,
                    )
                    await ledger.attach_artifact(
                        prev_state["run_id"],
                        data=data,
                        kind="transcript",
                        actor=actor,
                        name=(
                            f"transcript-{source}-"
                            f"{prev_state['step_run_id'][:12]}.json"
                        ),
                        content_type="application/json",
                        step_run_id=prev_state["step_run_id"],
                    )
                else:
                    logger.debug(
                        "Transcript path does not exist: %s", transcript_path
                    )
            else:
                logger.debug("No transcript_path in hook input.")

            # Complete the previous step
            await ledger.complete_step(
                prev_state["step_run_id"],
                actor=actor,
                summary=f"Session closed (new session: {source})",
            )
            logger.debug(
                "Completed previous step %s", prev_state["step_run_id"]
            )
    except Exception:
        # Log but don't fail — we still want the new session to start
        logger.exception(
            "Failed to close previous session (step %s)",
            prev_state["step_run_id"],
        )

    _clear_state()


@app.command()
@async_command
async def start(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output as JSON")
    ] = False,
) -> None:
    """Start or resume a session. Used by SessionStart hook.

    Handles Claude Code's SessionStart source field:
      - startup/clear: Full resume/create logic, new step.
      - compact: Post-compaction. Re-inject context from state file.
      - resume: Check existing state file, re-inject or create new.

    Resume logic (for startup/clear/new resume):
      1. HANNO_RUN_ID env var -> attach to existing run
      2. HANNO_SESSION_ID env var -> attach to existing session
      3. HANNO_REF env var (system:type:id) -> find/create session by ref
      4. Auto-create new run
    """
    _setup_debug_logging()
    hook_input = _read_hook_input()
    session_id = hook_input.get("session_id", "")
    source = hook_input.get("source", "startup")

    logger.debug(
        "SessionStart: source=%s session_id=%s hook_keys=%s",
        source,
        session_id,
        list(hook_input.keys()),
    )

    # Post-compaction: PreCompact already rotated the step.
    # Just re-inject context from the state file.
    if source == "compact":
        state = _read_state()
        if state is not None:
            logger.debug("Post-compaction: re-injecting state for run %s", state["run_id"])
            if json_output:
                print(json.dumps(state, default=str))  # noqa: T201
            else:
                async with open_ledger() as ledger:
                    run = await ledger.get_run(state["run_id"])
                if run:
                    print(_context_message(  # noqa: T201
                        run, state["step_run_id"],
                        action="Resumed (post-compaction)",
                    ))
        return

    # Resume: check if we have an active session for this session_id
    if source == "resume":
        state = _read_state()
        if state is not None and state.get("session_id") == session_id:
            logger.debug("Resume: matching session found for %s", session_id)
            if json_output:
                print(json.dumps(state, default=str))  # noqa: T201
            else:
                async with open_ledger() as ledger:
                    run = await ledger.get_run(state["run_id"])
                if run:
                    print(_context_message(  # noqa: T201
                        run, state["step_run_id"],
                        action="Resumed",
                    ))
            return
        logger.debug("Resume: no matching state for session %s — creating new", session_id)
        # No matching state — fall through to create new session

    # Close out any previous session before starting a new one
    await _close_previous_session(hook_input, source=source)

    # Full start logic (startup, clear, or resume without matching state)
    actor = _actor()
    run_type = os.environ.get("HANNO_RUN_TYPE", "claude_session")

    async with open_ledger() as ledger:
        run = None
        created = False
        hanno_session_id: str | None = None

        # 1. Check HANNO_RUN_ID — attach to an existing run directly
        run_id_env = os.environ.get("HANNO_RUN_ID")
        if run_id_env:
            logger.debug("HANNO_RUN_ID=%s", run_id_env)
            run = await ledger.get_run(run_id_env)
            if run is None:
                err_console.print(
                    f"[red]Run not found: {run_id_env}[/red]",
                )
                raise typer.Exit(1)
            hanno_session_id = run.session_id

        # 2. Check HANNO_SESSION_ID — attach to an explicit session
        if run is None:
            session_id_env = os.environ.get("HANNO_SESSION_ID")
            if session_id_env:
                logger.debug("HANNO_SESSION_ID=%s", session_id_env)
                hanno_session = await ledger.get_session(session_id_env)
                if hanno_session is None:
                    err_console.print(
                        f"[red]Session not found: {session_id_env}[/red]",
                    )
                    raise typer.Exit(1)
                hanno_session_id = hanno_session.id

        # 3. Check HANNO_REF — find/create session by external ref
        if run is None:
            ref_str = os.environ.get("HANNO_REF")
            if ref_str:
                logger.debug("HANNO_REF=%s", ref_str)
                ref = _parse_ref(ref_str)
                if ref is None:
                    err_console.print(
                        f"[red]Invalid HANNO_REF: {ref_str}"
                        " (expected system:type:id)[/red]",
                    )
                    raise typer.Exit(1)

                # Find or create a session for this ref
                if hanno_session_id is None:
                    sessions = await ledger.find_sessions_by_external_ref(
                        system=ref.system,
                        ref_type=ref.ref_type,
                        ref_id=ref.ref_id,
                    )
                    if sessions:
                        hanno_session_id = sessions[0].id
                        logger.debug("Found session %s for ref", hanno_session_id)
                    else:
                        hanno_session = await ledger.create_session(
                            external_refs=[ref],
                        )
                        hanno_session_id = hanno_session.id
                        logger.debug("Created session %s for ref", hanno_session_id)

        # 4. Create the run (always a new run per invocation)
        if run is None:
            run = await ledger.create_run(
                run_type,
                actor=actor,
                session_id=hanno_session_id,
            )
            created = True

        logger.debug(
            "Run: id=%s status=%s created=%s session=%s",
            run.id, run.status, created, hanno_session_id,
        )

        # Start the run if it's still planned
        if run.status.value == "planned":
            run = await ledger.start_run(run.id, actor=actor)

        # Add a step for this session
        step_meta: dict[str, object] = {
            "session_id": session_id,
            "source": source,
        }
        if hook_input.get("cwd"):
            step_meta["cwd"] = hook_input["cwd"]

        step = await ledger.add_step(
            run.id,
            step_name="session",
            actor=actor,
            metadata=step_meta,
        )
        step = await ledger.start_step(step.id, actor=actor)

        logger.debug("New step started: %s", step.id)

        # Write state file
        state = {
            "run_id": run.id,
            "step_run_id": step.id,
            "session_id": session_id,
            "hanno_session_id": hanno_session_id,
            "started_at": datetime.now(UTC).isoformat(),
        }
        _write_state(state)

    if json_output:
        print(json.dumps(state, default=str))  # noqa: T201
    else:
        action = "Created" if created else "Resumed"
        print(_context_message(  # noqa: T201
            run, step.id, action=action,
            hanno_session_id=hanno_session_id,
        ))


@app.command()
@async_command
async def snapshot(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output as JSON")
    ] = False,
) -> None:
    """Snapshot transcript and rotate step. Used by PreCompact hook."""
    _setup_debug_logging()
    hook_input = _read_hook_input()
    transcript_path = hook_input.get("transcript_path")
    trigger = hook_input.get("trigger", "unknown")
    state = _read_state()
    actor = _actor()

    logger.debug(
        "Snapshot: trigger=%s transcript_path=%s state=%s",
        trigger,
        transcript_path,
        "present" if state else "none",
    )

    if state is None:
        err_console.print("[dim]No active session.[/dim]")
        raise typer.Exit(1)

    async with open_ledger() as ledger:
        # Attach transcript if available
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

        # Complete current step
        await ledger.complete_step(
            state["step_run_id"],
            actor=actor,
            summary=f"Session compacted ({trigger})",
        )

        # Start a new step for the continued session
        new_step = await ledger.add_step(
            state["run_id"],
            step_name="session",
            actor=actor,
            depends_on=[state["step_run_id"]],
            metadata={
                "session_id": state["session_id"],
                "after_compaction": True,
                "trigger": trigger,
            },
        )
        new_step = await ledger.start_step(new_step.id, actor=actor)

        # Update state file
        state["step_run_id"] = new_step.id
        _write_state(state)

    if json_output:
        print(json.dumps(state, default=str))  # noqa: T201
    else:
        print(  # noqa: T201
            f"[Hanno] Transcript saved. "
            f"New step {new_step.id} started (post-compaction)."
        )


@app.command()
@async_command
async def end(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output as JSON")
    ] = False,
) -> None:
    """End session and attach final transcript. Used by SessionEnd hook."""
    _setup_debug_logging()
    hook_input = _read_hook_input()
    transcript_path = hook_input.get("transcript_path")
    reason = hook_input.get("reason", "unknown")
    state = _read_state()
    actor = _actor()

    logger.debug(
        "End: reason=%s transcript_path=%s state=%s",
        reason,
        transcript_path,
        "present" if state else "none",
    )

    if state is None:
        err_console.print("[dim]No active session.[/dim]")
        raise typer.Exit(1)

    async with open_ledger() as ledger:
        # Attach final transcript if available
        if transcript_path:
            path = Path(transcript_path)
            if path.exists():
                data = path.read_bytes()
                await ledger.attach_artifact(
                    state["run_id"],
                    data=data,
                    kind="transcript",
                    actor=actor,
                    name=(
                        f"transcript-final-"
                        f"{state['step_run_id'][:12]}.json"
                    ),
                    content_type="application/json",
                    step_run_id=state["step_run_id"],
                )

        # Complete the step
        await ledger.complete_step(
            state["step_run_id"],
            actor=actor,
            summary=f"Session ended ({reason})",
        )

    # Clear state file
    _clear_state()

    if json_output:
        result = {"ended": True, "run_id": state["run_id"]}
        print(json.dumps(result))  # noqa: T201
    else:
        print(  # noqa: T201
            f"[Hanno] Session ended. "
            f"Step {state['step_run_id']} completed."
        )


DEFAULT_LOG_TOOLS = {"Bash", "Write", "Edit", "NotebookEdit"}


@app.command("log-tool")
@async_command
async def log_tool() -> None:
    """Log a tool use as a note on the current step. Used by PostToolUse hook.

    Filters by HANNO_LOG_TOOLS env var (comma-separated tool names).
    Default: Bash,Write,Edit,NotebookEdit
    """
    _setup_debug_logging()
    hook_input = _read_hook_input()
    tool_name = hook_input.get("tool_name", "")
    logger.debug("LogTool: tool_name=%s", tool_name)

    # Filter: only log interesting tools
    log_tools_env = os.environ.get("HANNO_LOG_TOOLS")
    if log_tools_env is not None:
        allowed = {t.strip() for t in log_tools_env.split(",")}
    else:
        allowed = DEFAULT_LOG_TOOLS

    if tool_name not in allowed:
        return

    state = _read_state()
    if state is None:
        return  # silently skip if no active session

    tool_input = hook_input.get("tool_input", {})

    # Build a concise message
    if tool_name == "Bash":
        detail = tool_input.get("command", "")
        if len(detail) > 200:  # noqa: PLR2004
            detail = detail[:200] + "..."
        message = f"[tool] Bash: {detail}"
    elif tool_name in {"Write", "Edit"}:
        file_path = tool_input.get("file_path", "")
        message = f"[tool] {tool_name}: {file_path}"
    else:
        message = f"[tool] {tool_name}"

    actor = _actor()
    async with open_ledger() as ledger:
        await ledger.add_note(
            state["run_id"],
            actor=actor,
            message=message,
            step_run_id=state["step_run_id"],
        )


@app.command("log-stop")
@async_command
async def log_stop() -> None:
    """Log an agent stop event. Used by Stop hook."""
    _setup_debug_logging()
    hook_input = _read_hook_input()
    state = _read_state()
    if state is None:
        logger.debug("LogStop: no active session, skipping.")
        return
    logger.debug("LogStop: run=%s step=%s", state["run_id"], state["step_run_id"])

    stop_active = hook_input.get("stop_hook_active", False)
    message = "[stop] Agent finished responding"
    if stop_active:
        message += " (stop hook active)"

    actor = _actor()
    async with open_ledger() as ledger:
        await ledger.add_note(
            state["run_id"],
            actor=actor,
            message=message,
            step_run_id=state["step_run_id"],
        )


@app.command("list")
@async_command
async def list_sessions(
    status: Annotated[
        str | None, typer.Option(help="Filter by status (active, closed, archived)")
    ] = None,
    limit: Annotated[int, typer.Option(help="Max results")] = 20,
    json_output: Annotated[
        bool, typer.Option("--json", help="Output as JSON")
    ] = False,
) -> None:
    """List Hanno sessions."""
    from hanno_core.models import SessionStatus

    kwargs: dict[str, object] = {"limit": limit}
    if status is not None:
        try:
            kwargs["status"] = SessionStatus(status)
        except ValueError:
            err_console.print(f"[red]Invalid status: {status}[/red]")
            raise typer.Exit(1) from None

    async with open_ledger() as ledger:
        sessions = await ledger.list_sessions(**kwargs)

    if json_output:
        print("[" + ",".join(s.model_dump_json() for s in sessions) + "]")  # noqa: T201
    else:
        if not sessions:
            console.print("[dim]No sessions found.[/dim]")
            return
        for s in sessions:
            ref_str = ""
            if s.external_refs:
                r = s.external_refs[0]
                ref_str = f" [{r.system}:{r.ref_type}:{r.ref_id}]"
            title_str = f' "{s.title}"' if s.title else ""
            console.print(
                f"  {s.id}  {s.status.value:<8}{title_str}{ref_str}"
            )


@app.command("show")
@async_command
async def show_session(
    session_id: Annotated[str, typer.Argument(help="Session ID")],
    json_output: Annotated[
        bool, typer.Option("--json", help="Output as JSON")
    ] = False,
) -> None:
    """Show session details and its runs."""
    async with open_ledger() as ledger:
        hanno_session = await ledger.get_session(session_id)
        if hanno_session is None:
            err_console.print(f"[red]Session not found: {session_id}[/red]")
            raise typer.Exit(1)

        runs = await ledger.list_session_runs(session_id)

    if json_output:
        result = {
            "session": json.loads(hanno_session.model_dump_json()),
            "runs": [json.loads(r.model_dump_json()) for r in runs],
        }
        print(json.dumps(result))  # noqa: T201
    else:
        title_str = f' "{hanno_session.title}"' if hanno_session.title else ""
        console.print(f"Session {hanno_session.id}{title_str}")
        console.print(f"  Status: {hanno_session.status.value}")
        if hanno_session.external_refs:
            for ref in hanno_session.external_refs:
                console.print(f"  Ref: {ref.system}:{ref.ref_type}:{ref.ref_id}")
        if hanno_session.labels:
            console.print(f"  Labels: {hanno_session.labels}")
        console.print(f"  Created: {hanno_session.created_at}")

        if runs:
            console.print(f"\n  Runs ({len(runs)}):")
            for r in runs:
                title_part = f' "{r.title}"' if r.title else ""
                console.print(
                    f"    {r.id}  {r.status.value:<10} {r.run_type}{title_part}"
                )
        else:
            console.print("\n  [dim]No runs yet.[/dim]")


HOOK_CONFIG = {
    "hooks": {
        "SessionStart": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "hanno session start",
                    }
                ]
            }
        ],
        "PreCompact": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "hanno session snapshot",
                    }
                ]
            }
        ],
        "PostToolUse": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "hanno session log-tool",
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
                        "command": "hanno session log-stop",
                        "async": True,
                    }
                ]
            }
        ],
        "SessionEnd": [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "hanno session end",
                    }
                ]
            }
        ],
    }
}


@app.command("hooks")
def show_hooks() -> None:
    """Print Claude Code hook configuration JSON.

    Copy this into your .claude/settings.json or
    ~/.claude/settings.json to enable automatic session tracking.
    """
    print(json.dumps(HOOK_CONFIG, indent=2))  # noqa: T201
