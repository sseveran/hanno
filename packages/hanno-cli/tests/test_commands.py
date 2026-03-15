"""Integration tests for CLI commands."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest
import typer
from hanno_cli.commands.search import _parse_datetime_filter, _parse_entity_types
from hanno_cli.main import app
from hanno_core.models.search import EntityType
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


def _create_run(run_type: str = "test", title: str = "Test") -> str:
    """Helper to create a run and return its ID."""
    result = runner.invoke(app, ["run", "create", run_type, "--title", title, "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    return data["id"]


class TestRunCommands:
    def test_create(self):
        result = runner.invoke(app, ["run", "create", "deploy"])
        assert result.exit_code == 0
        assert "created (planned)" in result.output

    def test_create_json(self):
        result = runner.invoke(app, ["run", "create", "deploy", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["run_type"] == "deploy"
        assert data["status"] == "planned"

    def test_create_with_labels(self):
        result = runner.invoke(
            app,
            ["run", "create", "deploy", "-l", "env=staging", "-l", "team=infra", "--json"],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["labels"] == {"env": "staging", "team": "infra"}

    def test_list_empty(self):
        result = runner.invoke(app, ["run", "list"])
        assert result.exit_code == 0
        assert "No runs" in result.output

    def test_list_with_runs(self):
        _create_run()
        _create_run(run_type="other")
        result = runner.invoke(app, ["run", "list"])
        assert result.exit_code == 0
        assert "test" in result.output
        assert "other" in result.output

    def test_list_json(self):
        _create_run()
        result = runner.invoke(app, ["run", "list", "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1

    def test_show(self):
        run_id = _create_run()
        result = runner.invoke(app, ["run", "show", run_id])
        assert result.exit_code == 0
        assert "planned" in result.output

    def test_show_not_found(self):
        result = runner.invoke(app, ["run", "show", "nonexistent"])
        assert result.exit_code == 1

    def test_start(self):
        run_id = _create_run()
        result = runner.invoke(app, ["run", "start", run_id])
        assert result.exit_code == 0
        assert "started" in result.output

    def test_complete(self):
        run_id = _create_run()
        runner.invoke(app, ["run", "start", run_id])
        result = runner.invoke(app, ["run", "complete", run_id])
        assert result.exit_code == 0
        assert "completed" in result.output

    def test_fail(self):
        run_id = _create_run()
        runner.invoke(app, ["run", "start", run_id])
        result = runner.invoke(
            app, ["run", "fail", run_id, "--error", "oops"]
        )
        assert result.exit_code == 0
        assert "failed" in result.output

    def test_cancel(self):
        run_id = _create_run()
        result = runner.invoke(
            app, ["run", "cancel", run_id, "--reason", "not needed"]
        )
        assert result.exit_code == 0
        assert "canceled" in result.output


class TestStepCommands:
    def test_add_step(self):
        run_id = _create_run()
        result = runner.invoke(app, ["step", "add", run_id, "build"])
        assert result.exit_code == 0
        assert "added (build)" in result.output

    def test_add_step_json(self):
        run_id = _create_run()
        result = runner.invoke(
            app, ["step", "add", run_id, "build", "--json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["step_name"] == "build"

    def test_step_lifecycle(self):
        run_id = _create_run()
        # Add
        res = runner.invoke(app, ["step", "add", run_id, "build", "--json"])
        step_id = json.loads(res.output)["id"]

        # Start
        res = runner.invoke(app, ["step", "start", step_id])
        assert res.exit_code == 0
        assert "started" in res.output

        # Complete
        res = runner.invoke(
            app, ["step", "complete", step_id, "--summary", "done"]
        )
        assert res.exit_code == 0
        assert "completed" in res.output

    def test_fail_step(self):
        run_id = _create_run()
        res = runner.invoke(app, ["step", "add", run_id, "build", "--json"])
        step_id = json.loads(res.output)["id"]
        runner.invoke(app, ["step", "start", step_id])
        res = runner.invoke(
            app, ["step", "fail", step_id, "--error", "compile error"]
        )
        assert res.exit_code == 0
        assert "failed" in res.output

    def test_list_steps(self):
        run_id = _create_run()
        runner.invoke(app, ["step", "add", run_id, "build"])
        runner.invoke(app, ["step", "add", run_id, "test"])
        result = runner.invoke(app, ["step", "list", run_id])
        assert result.exit_code == 0
        assert "build" in result.output
        assert "test" in result.output


class TestEventCommands:
    def test_list_events(self):
        run_id = _create_run()
        result = runner.invoke(app, ["event", "list", run_id])
        assert result.exit_code == 0
        assert "run.created" in result.output

    def test_add_note(self):
        run_id = _create_run()
        result = runner.invoke(
            app, ["event", "note", run_id, "This is a note"]
        )
        assert result.exit_code == 0
        assert "Note added" in result.output

    def test_list_events_json(self):
        run_id = _create_run()
        result = runner.invoke(app, ["event", "list", run_id, "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) >= 1


class TestArtifactCommands:
    def test_attach(self, tmp_path: Path):
        run_id = _create_run()
        test_file = tmp_path / "test.log"
        test_file.write_text("log content")
        result = runner.invoke(
            app,
            ["artifact", "attach", run_id, str(test_file), "--kind", "log"],
        )
        assert result.exit_code == 0
        assert "attached" in result.output

    def test_attach_nonexistent(self):
        run_id = _create_run()
        result = runner.invoke(
            app, ["artifact", "attach", run_id, "/nonexistent"]
        )
        assert result.exit_code == 1

    def test_list_artifacts(self, tmp_path: Path):
        run_id = _create_run()
        test_file = tmp_path / "test.log"
        test_file.write_text("content")
        runner.invoke(
            app, ["artifact", "attach", run_id, str(test_file)]
        )
        result = runner.invoke(app, ["artifact", "list", run_id])
        assert result.exit_code == 0
        assert "test.log" in result.output


class TestApprovalCommands:
    def test_request_and_grant(self):
        run_id = _create_run()
        res = runner.invoke(
            app,
            [
                "approval", "request", run_id,
                "--authority", "github",
                "--resource", "pr/1",
                "--json",
            ],
        )
        assert res.exit_code == 0
        approval_id = json.loads(res.output)["id"]

        res = runner.invoke(app, ["approval", "grant", approval_id])
        assert res.exit_code == 0
        assert "granted" in res.output

    def test_request_and_deny(self):
        run_id = _create_run()
        res = runner.invoke(
            app, ["approval", "request", run_id, "--json"]
        )
        approval_id = json.loads(res.output)["id"]

        res = runner.invoke(
            app,
            ["approval", "deny", approval_id, "--reason", "needs fixes"],
        )
        assert res.exit_code == 0
        assert "denied" in res.output

    def test_list_approvals(self):
        run_id = _create_run()
        runner.invoke(app, ["approval", "request", run_id])
        result = runner.invoke(app, ["approval", "list", run_id])
        assert result.exit_code == 0
        assert "pending" in result.output


class TestSearchHelpers:
    def test_parse_entity_types(self):
        parsed = _parse_entity_types(["run", "event"])
        assert parsed == {EntityType.RUN, EntityType.EVENT}

    def test_parse_entity_types_invalid(self):
        with pytest.raises(typer.BadParameter):
            _parse_entity_types(["bogus"])

    def test_parse_datetime_filter_converts_aware_values(self):
        parsed = _parse_datetime_filter("2026-03-15T08:00:00+02:00", option_name="--after")
        assert parsed == datetime(2026, 3, 15, 6, 0, tzinfo=UTC)

    def test_parse_datetime_filter_assumes_utc_for_naive_values(self):
        parsed = _parse_datetime_filter("2026-03-15T08:00:00", option_name="--after")
        assert parsed == datetime(2026, 3, 15, 8, 0, tzinfo=UTC)


class TestSearchCommands:
    def test_query_invalid_type_returns_bad_parameter(self):
        result = runner.invoke(app, ["search", "query", "deploy", "--type", "bogus"])
        assert result.exit_code == 2
        assert "Invalid entity type" in result.output
