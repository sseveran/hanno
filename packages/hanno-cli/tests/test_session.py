"""Tests for session lifecycle commands."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from hanno_cli.commands.session import STATE_FILENAME
from hanno_cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture(autouse=True)
def _temp_db(tmp_path: Path):
    """Use a temp database for each test."""
    db_path = str(tmp_path / "test.db")
    art_path = str(tmp_path / "artifacts")
    with patch.dict(
        os.environ,
        {"HANNO_DB_PATH": db_path, "HANNO_ARTIFACT_PATH": art_path},
    ):
        yield


def _state_path() -> Path:
    return Path(os.environ["HANNO_DB_PATH"]).parent / STATE_FILENAME


def _create_run(
    run_type: str = "test", title: str = "Test",
) -> str:
    result = runner.invoke(
        app,
        ["run", "create", run_type, "--title", title, "--json"],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["id"]


def _hook_input(**kwargs: object) -> str:
    """Build a Claude Code hook input JSON string."""
    base = {
        "session_id": "test-session-001",
        "transcript_path": "",
        "cwd": "/test/project",
        "permission_mode": "default",
        "hook_event_name": "SessionStart",
    }
    base.update(kwargs)
    return json.dumps(base)


# --- SessionStart ---


class TestSessionStartBasic:
    def test_auto_create(self):
        inp = _hook_input(source="startup")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert "run_id" in data
        assert "step_run_id" in data

        # Verify state file
        state = json.loads(_state_path().read_text())
        assert state["run_id"] == data["run_id"]

    def test_context_injection_output(self):
        inp = _hook_input(source="startup")
        result = runner.invoke(
            app, ["session", "start"], input=inp,
        )
        assert result.exit_code == 0
        assert "[Hanno] Created run" in result.output
        assert "Step" in result.output

    def test_stores_session_id(self):
        inp = _hook_input(
            source="startup", session_id="my-session-xyz",
        )
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["session_id"] == "my-session-xyz"

    def test_stores_cwd_in_metadata(self):
        inp = _hook_input(source="startup", cwd="/home/user/project")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)

        # Check step metadata via CLI
        step_result = runner.invoke(
            app,
            ["step", "list", data["run_id"], "--json"],
        )
        steps = json.loads(step_result.output)
        assert steps[0]["metadata"]["cwd"] == "/home/user/project"

    def test_custom_run_type(self):
        with patch.dict(os.environ, {"HANNO_RUN_TYPE": "pr_review"}):
            inp = _hook_input(source="startup")
            result = runner.invoke(
                app, ["session", "start", "--json"], input=inp,
            )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)

        run_result = runner.invoke(
            app, ["run", "show", data["run_id"], "--json"],
        )
        run_data = json.loads(run_result.output)
        assert run_data["run_type"] == "pr_review"


class TestSessionStartResume:
    def test_resume_by_run_id(self):
        run_id = _create_run()
        with patch.dict(os.environ, {"HANNO_RUN_ID": run_id}):
            inp = _hook_input(source="startup")
            result = runner.invoke(
                app, ["session", "start", "--json"], input=inp,
            )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["run_id"] == run_id

    def test_resume_by_run_id_not_found(self):
        with patch.dict(os.environ, {"HANNO_RUN_ID": "nonexistent"}):
            inp = _hook_input(source="startup")
            result = runner.invoke(
                app, ["session", "start"], input=inp,
            )
        assert result.exit_code == 1

    def test_ref_creates_session_and_run(self):
        """HANNO_REF creates a Session for the ref and a new Run within it."""
        with patch.dict(
            os.environ, {"HANNO_REF": "github:pr:org/repo#99"},
        ):
            inp = _hook_input(source="startup")
            result = runner.invoke(
                app, ["session", "start", "--json"], input=inp,
            )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["hanno_session_id"] is not None

        # Run should be linked to the session
        run_result = runner.invoke(
            app, ["run", "show", data["run_id"], "--json"],
        )
        run_data = json.loads(run_result.output)
        assert run_data["session_id"] == data["hanno_session_id"]

    def test_ref_reuses_existing_session(self):
        """Second invocation with same HANNO_REF reuses the Session."""
        ref = "github:pr:org/repo#42"
        with patch.dict(os.environ, {"HANNO_REF": ref}):
            inp = _hook_input(source="startup", session_id="s1")
            result = runner.invoke(
                app, ["session", "start", "--json"], input=inp,
            )
        assert result.exit_code == 0, result.output
        data1 = json.loads(result.output)

        # End first session
        inp = _hook_input(hook_event_name="SessionEnd", reason="done")
        runner.invoke(app, ["session", "end"], input=inp)

        # Second invocation with same ref
        with patch.dict(os.environ, {"HANNO_REF": ref}):
            inp = _hook_input(source="startup", session_id="s2")
            result = runner.invoke(
                app, ["session", "start", "--json"], input=inp,
            )
        assert result.exit_code == 0, result.output
        data2 = json.loads(result.output)

        # Same session, different run
        assert data2["hanno_session_id"] == data1["hanno_session_id"]
        assert data2["run_id"] != data1["run_id"]

    def test_invalid_ref(self):
        with patch.dict(os.environ, {"HANNO_REF": "bad-format"}):
            inp = _hook_input(source="startup")
            result = runner.invoke(
                app, ["session", "start"], input=inp,
            )
        assert result.exit_code == 1


class TestSessionStartSource:
    """Test handling of Claude Code's source field."""

    def test_source_compact_reuses_state(self):
        """After compaction, SessionStart(source=compact) should
        re-inject context without creating a new step."""
        # Start a session (creates run + step)
        inp = _hook_input(source="startup")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        state1 = json.loads(result.output)

        # Simulate PreCompact (rotates step)
        inp = _hook_input(
            hook_event_name="PreCompact", trigger="auto",
        )
        result = runner.invoke(
            app, ["session", "snapshot", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        state2 = json.loads(result.output)
        assert state2["step_run_id"] != state1["step_run_id"]

        # Now SessionStart(source=compact) — should NOT create step
        inp = _hook_input(source="compact")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        state3 = json.loads(result.output)
        # Should have the same step as after snapshot
        assert state3["step_run_id"] == state2["step_run_id"]
        assert state3["run_id"] == state1["run_id"]

    def test_source_compact_human_output(self):
        inp = _hook_input(source="startup")
        runner.invoke(app, ["session", "start"], input=inp)

        # Snapshot
        runner.invoke(
            app, ["session", "snapshot"],
            input=_hook_input(
                hook_event_name="PreCompact", trigger="auto",
            ),
        )

        # Compact
        inp = _hook_input(source="compact")
        result = runner.invoke(
            app, ["session", "start"], input=inp,
        )
        assert result.exit_code == 0
        assert "post-compaction" in result.output

    def test_source_compact_no_state(self):
        """If no state file exists, compact source is a no-op."""
        inp = _hook_input(source="compact")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        # Should exit cleanly with no output
        assert result.exit_code == 0

    def test_source_resume_with_matching_session(self):
        """Resume with matching session_id reuses state."""
        inp = _hook_input(
            source="startup", session_id="sess-abc",
        )
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        state1 = json.loads(result.output)

        # Resume same session
        inp = _hook_input(
            source="resume", session_id="sess-abc",
        )
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        state2 = json.loads(result.output)
        assert state2["step_run_id"] == state1["step_run_id"]

    def test_source_resume_different_session_creates_new(self):
        """Resume with different session_id creates a new step."""
        inp = _hook_input(
            source="startup", session_id="sess-abc",
        )
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        state1 = json.loads(result.output)

        # Resume different session
        inp = _hook_input(
            source="resume", session_id="sess-xyz",
        )
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        state2 = json.loads(result.output)
        # Different step (new session was created)
        assert state2["step_run_id"] != state1["step_run_id"]

    def test_source_clear_creates_new(self):
        """source=clear should create a new session."""
        inp = _hook_input(source="startup")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        state1 = json.loads(result.output)

        # Clear creates new session
        inp = _hook_input(source="clear")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        state2 = json.loads(result.output)
        assert state2["step_run_id"] != state1["step_run_id"]

    def test_clear_closes_previous_step(self):
        """source=clear should complete the previous step."""
        inp = _hook_input(source="startup")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        state1 = json.loads(result.output)

        # Clear — should close prev step then create new
        inp = _hook_input(source="clear")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output

        # Previous step should be completed
        step_result = runner.invoke(
            app, ["step", "list", state1["run_id"], "--json"],
        )
        steps = json.loads(step_result.output)
        old_step = [
            s for s in steps if s["id"] == state1["step_run_id"]
        ]
        assert len(old_step) == 1
        assert old_step[0]["status"] == "succeeded"

    def test_clear_attaches_transcript(self, tmp_path: Path):
        """source=clear should attach transcript from previous session."""
        inp = _hook_input(source="startup")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        state1 = json.loads(result.output)

        # Create a transcript file
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text('{"role":"user","content":"hello"}\n')

        # Clear with transcript_path
        inp = _hook_input(
            source="clear",
            transcript_path=str(transcript),
        )
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output

        # Transcript should be attached
        art_result = runner.invoke(
            app, ["artifact", "list", state1["run_id"], "--json"],
        )
        arts = json.loads(art_result.output)
        assert len(arts) == 1
        assert arts[0]["kind"] == "transcript"
        assert "clear" in arts[0]["name"]

    def test_startup_closes_previous_step(self):
        """A new startup should close any dangling previous step."""
        inp = _hook_input(source="startup", session_id="s1")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        state1 = json.loads(result.output)

        # New startup without ending previous
        inp = _hook_input(source="startup", session_id="s2")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output

        # Previous step should be completed
        step_result = runner.invoke(
            app, ["step", "list", state1["run_id"], "--json"],
        )
        steps = json.loads(step_result.output)
        old_step = [
            s for s in steps if s["id"] == state1["step_run_id"]
        ]
        assert len(old_step) == 1
        assert old_step[0]["status"] == "succeeded"

    def test_resume_different_session_closes_previous(self):
        """Resume with different session_id should close previous step."""
        inp = _hook_input(source="startup", session_id="s1")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        state1 = json.loads(result.output)

        # Resume with different session — falls through to full start
        inp = _hook_input(source="resume", session_id="s-different")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output

        # Previous step should be completed
        step_result = runner.invoke(
            app, ["step", "list", state1["run_id"], "--json"],
        )
        steps = json.loads(step_result.output)
        old_step = [
            s for s in steps if s["id"] == state1["step_run_id"]
        ]
        assert len(old_step) == 1
        assert old_step[0]["status"] == "succeeded"


# --- Snapshot ---


class TestSessionSnapshot:
    def _start_session(self) -> dict:
        inp = _hook_input(source="startup")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        return json.loads(result.output)

    def test_no_session(self):
        result = runner.invoke(
            app, ["session", "snapshot"], input="{}",
        )
        assert result.exit_code == 1

    def test_rotates_step(self):
        state = self._start_session()
        old_step_id = state["step_run_id"]

        inp = _hook_input(
            hook_event_name="PreCompact", trigger="auto",
        )
        result = runner.invoke(
            app, ["session", "snapshot", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        new_state = json.loads(result.output)
        assert new_state["step_run_id"] != old_step_id
        assert new_state["run_id"] == state["run_id"]

    def test_attaches_transcript(self, tmp_path: Path):
        state = self._start_session()

        transcript = tmp_path / "transcript.json"
        content = {
            "messages": [{"role": "user", "content": "hello"}],
        }
        transcript.write_text(json.dumps(content))

        inp = _hook_input(
            hook_event_name="PreCompact",
            trigger="auto",
            transcript_path=str(transcript),
        )
        result = runner.invoke(
            app, ["session", "snapshot", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output

        art_result = runner.invoke(
            app, ["artifact", "list", state["run_id"], "--json"],
        )
        arts = json.loads(art_result.output)
        assert len(arts) == 1
        assert arts[0]["kind"] == "transcript"

    def test_records_trigger(self):
        state = self._start_session()

        inp = _hook_input(
            hook_event_name="PreCompact", trigger="manual",
        )
        runner.invoke(
            app, ["session", "snapshot", "--json"], input=inp,
        )

        # Check step summary
        step_result = runner.invoke(
            app,
            ["step", "list", state["run_id"], "--json"],
        )
        steps = json.loads(step_result.output)
        completed = [s for s in steps if s["status"] == "succeeded"]
        assert "manual" in completed[0]["summary"]


# --- End ---


class TestSessionEnd:
    def _start_session(self) -> dict:
        inp = _hook_input(source="startup")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        return json.loads(result.output)

    def test_no_session(self):
        result = runner.invoke(
            app, ["session", "end"], input="{}",
        )
        assert result.exit_code == 1

    def test_completes_step(self):
        state = self._start_session()

        inp = _hook_input(
            hook_event_name="SessionEnd", reason="logout",
        )
        result = runner.invoke(
            app, ["session", "end"], input=inp,
        )
        assert result.exit_code == 0
        assert "ended" in result.output
        assert not _state_path().exists()

        step_result = runner.invoke(
            app,
            ["step", "list", state["run_id"], "--json"],
        )
        steps = json.loads(step_result.output)
        assert steps[0]["status"] == "succeeded"
        assert "logout" in steps[0]["summary"]

    def test_attaches_transcript(self, tmp_path: Path):
        state = self._start_session()

        transcript = tmp_path / "transcript.json"
        transcript.write_text(json.dumps({"messages": []}))

        inp = _hook_input(
            hook_event_name="SessionEnd",
            reason="logout",
            transcript_path=str(transcript),
        )
        result = runner.invoke(
            app, ["session", "end"], input=inp,
        )
        assert result.exit_code == 0

        art_result = runner.invoke(
            app, ["artifact", "list", state["run_id"], "--json"],
        )
        arts = json.loads(art_result.output)
        assert len(arts) == 1
        assert arts[0]["kind"] == "transcript"
        assert "final" in arts[0]["name"]


# --- Full lifecycle ---


class TestFullLifecycle:
    def test_start_compact_end(self, tmp_path: Path):
        """Full realistic lifecycle:
        startup -> PreCompact -> SessionStart(compact) -> end.
        """
        t1 = tmp_path / "t1.json"
        t1.write_text('{"phase": "pre_compact"}')
        t2 = tmp_path / "t2.json"
        t2.write_text('{"phase": "final"}')

        # 1. SessionStart(startup)
        inp = _hook_input(source="startup", session_id="s1")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        state = json.loads(result.output)
        step1 = state["step_run_id"]

        # 2. PreCompact
        inp = _hook_input(
            hook_event_name="PreCompact",
            trigger="auto",
            transcript_path=str(t1),
            session_id="s1",
        )
        result = runner.invoke(
            app, ["session", "snapshot", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        state2 = json.loads(result.output)
        step2 = state2["step_run_id"]
        assert step2 != step1

        # 3. SessionStart(compact) — should not create new step
        inp = _hook_input(source="compact", session_id="s1")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        state3 = json.loads(result.output)
        assert state3["step_run_id"] == step2

        # 4. SessionEnd
        inp = _hook_input(
            hook_event_name="SessionEnd",
            reason="logout",
            transcript_path=str(t2),
            session_id="s1",
        )
        result = runner.invoke(
            app, ["session", "end"], input=inp,
        )
        assert result.exit_code == 0

        # Verify: 2 steps, 2 artifacts
        run_id = state["run_id"]
        step_result = runner.invoke(
            app, ["step", "list", run_id, "--json"],
        )
        steps = json.loads(step_result.output)
        assert len(steps) == 2
        assert all(s["status"] == "succeeded" for s in steps)

        art_result = runner.invoke(
            app, ["artifact", "list", run_id, "--json"],
        )
        arts = json.loads(art_result.output)
        assert len(arts) == 2

    def test_multi_session_on_same_run(self):
        """Multiple sessions attach to the same run via HANNO_RUN_ID."""
        # First session
        inp = _hook_input(source="startup", session_id="s1")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        state1 = json.loads(result.output)
        run_id = state1["run_id"]

        # End first session
        inp = _hook_input(
            hook_event_name="SessionEnd", reason="logout",
        )
        runner.invoke(app, ["session", "end"], input=inp)

        # Second session on same run
        with patch.dict(os.environ, {"HANNO_RUN_ID": run_id}):
            inp = _hook_input(source="startup", session_id="s2")
            result = runner.invoke(
                app, ["session", "start", "--json"], input=inp,
            )
        assert result.exit_code == 0, result.output
        state2 = json.loads(result.output)
        assert state2["run_id"] == run_id
        assert state2["step_run_id"] != state1["step_run_id"]

        # End second session
        inp = _hook_input(
            hook_event_name="SessionEnd", reason="logout",
        )
        runner.invoke(app, ["session", "end"], input=inp)

        # Verify: 2 steps on the run
        step_result = runner.invoke(
            app, ["step", "list", run_id, "--json"],
        )
        steps = json.loads(step_result.output)
        assert len(steps) == 2


# --- Tool logging ---


class TestLogTool:
    def _start_session(self) -> dict:
        inp = _hook_input(source="startup")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        return json.loads(result.output)

    def test_logs_bash_command(self):
        state = self._start_session()
        inp = _hook_input(
            hook_event_name="PostToolUse",
            tool_name="Bash",
            tool_input={"command": "npm test"},
        )
        result = runner.invoke(
            app, ["session", "log-tool"], input=inp,
        )
        assert result.exit_code == 0

        # Verify note was added
        ev_result = runner.invoke(
            app, ["event", "list", state["run_id"], "--json"],
        )
        events = json.loads(ev_result.output)
        notes = [
            e for e in events if e["kind"] == "note"
        ]
        assert len(notes) == 1
        assert "Bash" in notes[0]["payload"]["message"]
        assert "npm test" in notes[0]["payload"]["message"]

    def test_logs_write(self):
        state = self._start_session()
        inp = _hook_input(
            hook_event_name="PostToolUse",
            tool_name="Write",
            tool_input={"file_path": "/src/main.py"},
        )
        result = runner.invoke(
            app, ["session", "log-tool"], input=inp,
        )
        assert result.exit_code == 0

        ev_result = runner.invoke(
            app, ["event", "list", state["run_id"], "--json"],
        )
        events = json.loads(ev_result.output)
        notes = [e for e in events if e["kind"] == "note"]
        assert len(notes) == 1
        assert "Write" in notes[0]["payload"]["message"]
        assert "/src/main.py" in notes[0]["payload"]["message"]

    def test_logs_edit(self):
        state = self._start_session()
        inp = _hook_input(
            hook_event_name="PostToolUse",
            tool_name="Edit",
            tool_input={"file_path": "/src/utils.py"},
        )
        runner.invoke(app, ["session", "log-tool"], input=inp)

        ev_result = runner.invoke(
            app, ["event", "list", state["run_id"], "--json"],
        )
        events = json.loads(ev_result.output)
        notes = [e for e in events if e["kind"] == "note"]
        assert len(notes) == 1
        assert "Edit" in notes[0]["payload"]["message"]

    def test_skips_read_tool(self):
        state = self._start_session()
        inp = _hook_input(
            hook_event_name="PostToolUse",
            tool_name="Read",
            tool_input={"file_path": "/src/main.py"},
        )
        runner.invoke(app, ["session", "log-tool"], input=inp)

        ev_result = runner.invoke(
            app, ["event", "list", state["run_id"], "--json"],
        )
        events = json.loads(ev_result.output)
        notes = [e for e in events if e["kind"] == "note"]
        assert len(notes) == 0

    def test_skips_grep_glob(self):
        state = self._start_session()
        for tool in ["Grep", "Glob"]:
            inp = _hook_input(
                hook_event_name="PostToolUse",
                tool_name=tool,
                tool_input={},
            )
            runner.invoke(app, ["session", "log-tool"], input=inp)

        ev_result = runner.invoke(
            app, ["event", "list", state["run_id"], "--json"],
        )
        events = json.loads(ev_result.output)
        notes = [e for e in events if e["kind"] == "note"]
        assert len(notes) == 0

    def test_custom_log_tools(self):
        state = self._start_session()
        with patch.dict(
            os.environ, {"HANNO_LOG_TOOLS": "Read,Grep"},
        ):
            # Read should now be logged
            inp = _hook_input(
                hook_event_name="PostToolUse",
                tool_name="Read",
                tool_input={"file_path": "/f.py"},
            )
            runner.invoke(
                app, ["session", "log-tool"], input=inp,
            )

            # Bash should now be skipped
            inp = _hook_input(
                hook_event_name="PostToolUse",
                tool_name="Bash",
                tool_input={"command": "ls"},
            )
            runner.invoke(
                app, ["session", "log-tool"], input=inp,
            )

        ev_result = runner.invoke(
            app, ["event", "list", state["run_id"], "--json"],
        )
        events = json.loads(ev_result.output)
        notes = [e for e in events if e["kind"] == "note"]
        assert len(notes) == 1
        assert "Read" in notes[0]["payload"]["message"]

    def test_truncates_long_bash_command(self):
        state = self._start_session()
        long_cmd = "x" * 300
        inp = _hook_input(
            hook_event_name="PostToolUse",
            tool_name="Bash",
            tool_input={"command": long_cmd},
        )
        runner.invoke(app, ["session", "log-tool"], input=inp)

        ev_result = runner.invoke(
            app, ["event", "list", state["run_id"], "--json"],
        )
        events = json.loads(ev_result.output)
        notes = [e for e in events if e["kind"] == "note"]
        msg = notes[0]["payload"]["message"]
        assert len(msg) < 250
        assert "..." in msg

    def test_no_session_silently_skips(self):
        inp = _hook_input(
            hook_event_name="PostToolUse",
            tool_name="Bash",
            tool_input={"command": "ls"},
        )
        result = runner.invoke(
            app, ["session", "log-tool"], input=inp,
        )
        assert result.exit_code == 0


# --- Stop logging ---


class TestLogStop:
    def _start_session(self) -> dict:
        inp = _hook_input(source="startup")
        result = runner.invoke(
            app, ["session", "start", "--json"], input=inp,
        )
        assert result.exit_code == 0, result.output
        return json.loads(result.output)

    def test_logs_stop(self):
        state = self._start_session()
        inp = _hook_input(
            hook_event_name="Stop", stop_hook_active=False,
        )
        result = runner.invoke(
            app, ["session", "log-stop"], input=inp,
        )
        assert result.exit_code == 0

        ev_result = runner.invoke(
            app, ["event", "list", state["run_id"], "--json"],
        )
        events = json.loads(ev_result.output)
        notes = [e for e in events if e["kind"] == "note"]
        assert len(notes) == 1
        assert "finished responding" in notes[0]["payload"]["message"]

    def test_stop_hook_active_flag(self):
        state = self._start_session()
        inp = _hook_input(
            hook_event_name="Stop", stop_hook_active=True,
        )
        runner.invoke(app, ["session", "log-stop"], input=inp)

        ev_result = runner.invoke(
            app, ["event", "list", state["run_id"], "--json"],
        )
        events = json.loads(ev_result.output)
        notes = [e for e in events if e["kind"] == "note"]
        assert "stop hook active" in notes[0]["payload"]["message"]

    def test_no_session_silently_skips(self):
        inp = _hook_input(hook_event_name="Stop")
        result = runner.invoke(
            app, ["session", "log-stop"], input=inp,
        )
        assert result.exit_code == 0


# --- Hooks config ---


class TestHooksCommand:
    def test_show_hooks(self):
        result = runner.invoke(app, ["session", "hooks"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "hooks" in data
        assert "SessionStart" in data["hooks"]
        assert "PreCompact" in data["hooks"]
        assert "PostToolUse" in data["hooks"]
        assert "Stop" in data["hooks"]
        assert "SessionEnd" in data["hooks"]

    def test_async_hooks(self):
        """PostToolUse and Stop should be async."""
        result = runner.invoke(app, ["session", "hooks"])
        data = json.loads(result.output)
        post_tool = data["hooks"]["PostToolUse"][0]["hooks"][0]
        assert post_tool["async"] is True
        stop = data["hooks"]["Stop"][0]["hooks"][0]
        assert stop["async"] is True


# --- Run find ---


class TestRunFind:
    def test_find_by_ref(self):
        runner.invoke(
            app,
            [
                "run", "create", "pr",
                "--ref", "github:issue:org/repo#42",
            ],
        )
        result = runner.invoke(
            app,
            [
                "run", "find",
                "--ref", "github:issue:org/repo#42",
                "--json",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1

    def test_find_no_match(self):
        result = runner.invoke(
            app,
            [
                "run", "find",
                "--ref", "github:issue:nonexistent",
                "--json",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 0

    def test_find_invalid_ref(self):
        result = runner.invoke(app, ["run", "find", "--ref", "bad"])
        assert result.exit_code == 1
