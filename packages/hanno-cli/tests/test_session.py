"""Tests for task hook lifecycle commands."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from hanno_cli.commands.task import STATE_FILENAME
from hanno_cli.main import app
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture(autouse=True)
def _temp_db(tmp_path: Path):
    db_path = str(tmp_path / "test.db")
    art_path = str(tmp_path / "artifacts")
    with patch.dict(
        os.environ,
        {"HANNO_DB_PATH": db_path, "HANNO_ARTIFACT_PATH": art_path},
    ):
        yield


def _state_path() -> Path:
    return Path(os.environ["HANNO_DB_PATH"]).parent / STATE_FILENAME


def _create_workspace(title: str = "Alpha") -> str:
    result = runner.invoke(app, ["workspace", "create", "--title", title, "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["id"]


def _create_repo(
    workspace_id: str,
    *,
    canonical_remote: str,
    local_path: str | None = None,
) -> str:
    args = [
        "workspace",
        "repo",
        "add",
        workspace_id,
        "--canonical-remote",
        canonical_remote,
        "--json",
    ]
    if local_path is not None:
        args.extend(["--local-path", local_path])
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["id"]


def _create_task(workspace_id: str, title: str = "PR #42") -> str:
    result = runner.invoke(
        app,
        ["task", "create", "--workspace-id", workspace_id, "--title", title, "--json"],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["id"]


def _hook_input(**kwargs: object) -> str:
    base = {
        "session_id": "tool-session-001",
        "transcript_path": "",
        "cwd": "/tmp/non-git",
        "permission_mode": "default",
        "hook_event_name": "SessionStart",
    }
    base.update(kwargs)
    return json.dumps(base)


def _init_git_repo(tmp_path: Path, name: str, remote: str) -> Path:
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "init", repo], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", remote],
        check=True,
        capture_output=True,
        text=True,
    )
    return repo


class TestTaskHookStart:
    def test_explicit_workspace_and_task_id(self):
        workspace_id = _create_workspace()
        task_id = _create_task(workspace_id)
        with patch.dict(
            os.environ,
            {"HANNO_WORKSPACE_ID": workspace_id, "HANNO_TASK_ID": task_id},
        ):
            result = runner.invoke(
                app,
                ["task", "start", "--json"],
                input=_hook_input(source="startup"),
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["workspace_id"] == workspace_id
        assert data["task_id"] == task_id
        assert _state_path().exists()

    def test_task_ref_creates_workspace_task_and_repo_from_git_context(self, tmp_path: Path):
        repo = _init_git_repo(tmp_path, "hanno", "git@github.com:OpenAI/hanno.git")
        with patch.dict(os.environ, {"HANNO_TASK_REF": "github:pr:openai/hanno#42"}):
            result = runner.invoke(
                app,
                ["task", "start", "--json"],
                input=_hook_input(source="startup", cwd=str(repo)),
            )

        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["workspace_id"]
        assert data["task_id"]
        assert data["workspace_repo_id"]

        task_result = runner.invoke(app, ["task", "show", data["task_id"], "--json"])
        task_data = json.loads(task_result.output)
        assert len(task_data["repos"]) == 1

    def test_reuses_existing_workspace_by_repo_context(self, tmp_path: Path):
        repo = _init_git_repo(tmp_path, "hanno", "git@github.com:OpenAI/hanno.git")
        workspace_id = _create_workspace()
        _create_repo(
            workspace_id,
            canonical_remote="github.com/openai/hanno",
            local_path=str(repo),
        )

        with patch.dict(os.environ, {"HANNO_TASK_REF": "github:pr:openai/hanno#42"}):
            result = runner.invoke(
                app,
                ["task", "start", "--json"],
                input=_hook_input(source="startup", cwd=str(repo)),
            )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["workspace_id"] == workspace_id

    def test_missing_task_hint_fails(self, tmp_path: Path):
        repo = _init_git_repo(tmp_path, "hanno", "git@github.com:OpenAI/hanno.git")
        result = runner.invoke(
            app,
            ["task", "start"],
            input=_hook_input(source="startup", cwd=str(repo)),
        )
        assert result.exit_code == 1

    def test_ambiguous_workspace_resolution_fails(self, tmp_path: Path):
        repo = _init_git_repo(tmp_path, "hanno", "git@github.com:OpenAI/hanno.git")
        ws1 = _create_workspace("One")
        ws2 = _create_workspace("Two")
        _create_repo(ws1, canonical_remote="github.com/openai/hanno")
        _create_repo(ws2, canonical_remote="github.com/openai/hanno")

        with patch.dict(os.environ, {"HANNO_TASK_REF": "github:pr:openai/hanno#42"}):
            result = runner.invoke(
                app,
                ["task", "start"],
                input=_hook_input(source="startup", cwd=str(repo)),
            )
        assert result.exit_code == 1

    def test_task_workspace_mismatch_fails(self):
        workspace_id = _create_workspace("One")
        other_workspace_id = _create_workspace("Two")
        task_id = _create_task(other_workspace_id)
        with patch.dict(
            os.environ,
            {"HANNO_WORKSPACE_ID": workspace_id, "HANNO_TASK_ID": task_id},
        ):
            result = runner.invoke(app, ["task", "start"], input=_hook_input(source="startup"))
        assert result.exit_code == 1


class TestTaskHookRotation:
    def _start(self, workspace_id: str, task_id: str) -> dict:
        with patch.dict(
            os.environ,
            {"HANNO_WORKSPACE_ID": workspace_id, "HANNO_TASK_ID": task_id},
        ):
            result = runner.invoke(
                app,
                ["task", "start", "--json"],
                input=_hook_input(source="startup"),
            )
        assert result.exit_code == 0, result.output
        return json.loads(result.output)

    def test_snapshot_rotates_step(self):
        workspace_id = _create_workspace()
        task_id = _create_task(workspace_id)
        state = self._start(workspace_id, task_id)
        result = runner.invoke(
            app,
            ["task", "snapshot", "--json"],
            input=_hook_input(hook_event_name="PreCompact", trigger="auto"),
        )
        assert result.exit_code == 0, result.output
        next_state = json.loads(result.output)
        assert next_state["step_run_id"] != state["step_run_id"]

    def test_end_clears_state(self):
        workspace_id = _create_workspace()
        task_id = _create_task(workspace_id)
        self._start(workspace_id, task_id)
        result = runner.invoke(
            app,
            ["task", "end", "--json"],
            input=_hook_input(hook_event_name="SessionEnd", reason="done"),
        )
        assert result.exit_code == 0, result.output
        assert not _state_path().exists()
