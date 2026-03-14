"""Integration tests for CLI commands."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
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


def _create_workspace(title: str = "Alpha") -> str:
    result = runner.invoke(app, ["workspace", "create", "--title", title, "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["id"]


def _create_task(workspace_id: str, title: str = "PR #42") -> str:
    result = runner.invoke(
        app,
        ["task", "create", "--workspace-id", workspace_id, "--title", title, "--json"],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["id"]


def _create_run(
    workspace_id: str,
    task_id: str | None = None,
    run_type: str = "test",
    title: str = "Test",
) -> str:
    args = [
        "run",
        "create",
        run_type,
        "--workspace-id",
        workspace_id,
        "--title",
        title,
        "--json",
    ]
    if task_id is not None:
        args.extend(["--task-id", task_id])
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["id"]


class TestWorkspaceCommands:
    def test_create_and_list(self):
        result = runner.invoke(app, ["workspace", "create", "--title", "Alpha"])
        assert result.exit_code == 0
        assert "created" in result.output

        result = runner.invoke(app, ["workspace", "list"])
        assert result.exit_code == 0
        assert "Alpha" in result.output


class TestTaskCommands:
    def test_create_show_and_close(self):
        workspace_id = _create_workspace()
        result = runner.invoke(
            app,
            ["task", "create", "--workspace-id", workspace_id, "--title", "Fix review"],
        )
        assert result.exit_code == 0

        task_id = _create_task(workspace_id)
        result = runner.invoke(app, ["task", "show", task_id])
        assert result.exit_code == 0
        assert workspace_id in result.output

        result = runner.invoke(app, ["task", "close", task_id])
        assert result.exit_code == 0
        assert "closed" in result.output


class TestRunCommands:
    def test_create_requires_workspace(self):
        result = runner.invoke(app, ["run", "create", "deploy"])
        assert result.exit_code != 0

    def test_create_json(self):
        workspace_id = _create_workspace()
        task_id = _create_task(workspace_id)
        result = runner.invoke(
            app,
            [
                "run",
                "create",
                "deploy",
                "--workspace-id",
                workspace_id,
                "--task-id",
                task_id,
                "--json",
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["run_type"] == "deploy"
        assert data["workspace_id"] == workspace_id
        assert data["task_id"] == task_id

    def test_list_and_show(self):
        workspace_id = _create_workspace()
        _create_run(workspace_id, run_type="test")
        _create_run(workspace_id, run_type="other")
        result = runner.invoke(app, ["run", "list", "--workspace-id", workspace_id])
        assert result.exit_code == 0
        assert "test" in result.output
        assert "other" in result.output

    def test_run_lifecycle(self):
        workspace_id = _create_workspace()
        run_id = _create_run(workspace_id)
        assert runner.invoke(app, ["run", "start", run_id]).exit_code == 0
        assert runner.invoke(app, ["run", "complete", run_id]).exit_code == 0


class TestStepCommands:
    def test_step_lifecycle(self):
        workspace_id = _create_workspace()
        run_id = _create_run(workspace_id)
        res = runner.invoke(app, ["step", "add", run_id, "build", "--json"])
        assert res.exit_code == 0
        step_id = json.loads(res.output)["id"]
        assert runner.invoke(app, ["step", "start", step_id]).exit_code == 0
        assert (
            runner.invoke(app, ["step", "complete", step_id, "--summary", "done"]).exit_code
            == 0
        )


class TestEventCommands:
    def test_add_note(self):
        workspace_id = _create_workspace()
        run_id = _create_run(workspace_id)
        result = runner.invoke(app, ["event", "note", run_id, "This is a note"])
        assert result.exit_code == 0
        assert "Note added" in result.output


class TestArtifactCommands:
    def test_attach_and_list(self, tmp_path: Path):
        workspace_id = _create_workspace()
        run_id = _create_run(workspace_id)
        test_file = tmp_path / "test.log"
        test_file.write_text("log content")
        result = runner.invoke(
            app,
            ["artifact", "attach", run_id, str(test_file), "--kind", "log"],
        )
        assert result.exit_code == 0
        result = runner.invoke(app, ["artifact", "list", run_id])
        assert result.exit_code == 0
        assert "test.log" in result.output


class TestApprovalCommands:
    def test_request_and_grant(self):
        workspace_id = _create_workspace()
        run_id = _create_run(workspace_id)
        res = runner.invoke(
            app,
            [
                "approval",
                "request",
                run_id,
                "--authority",
                "github",
                "--resource",
                "pr/1",
                "--json",
            ],
        )
        assert res.exit_code == 0
        approval_id = json.loads(res.output)["id"]
        res = runner.invoke(app, ["approval", "grant", approval_id])
        assert res.exit_code == 0
