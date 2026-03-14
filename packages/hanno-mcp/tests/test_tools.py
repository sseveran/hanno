"""Integration tests for MCP tools using in-memory transport."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from hanno_mcp.server import mcp
from mcp.shared.memory import create_connected_server_and_client_session


@pytest.fixture(autouse=True)
def _temp_db(tmp_path: Path):
    db_path = str(tmp_path / "test.db")
    art_path = str(tmp_path / "artifacts")
    with patch.dict(
        os.environ,
        {"HANNO_DB_PATH": db_path, "HANNO_ARTIFACT_PATH": art_path},
    ):
        yield


async def _call(session, name: str, args: dict | None = None) -> dict | list:
    result = await session.call_tool(name, args or {})
    text = result.content[0].text
    return json.loads(text)


class TestWorkspaceAndTaskTools:
    @pytest.mark.asyncio
    async def test_create_workspace_and_task(self):
        async with create_connected_server_and_client_session(mcp) as session:
            workspace = await _call(session, "hanno_create_workspace", {"title": "Alpha"})
            assert workspace["title"] == "Alpha"

            repo = await _call(
                session,
                "hanno_create_workspace_repo",
                {
                    "workspace_id": workspace["id"],
                    "display_name": "hanno",
                    "canonical_remote": "github.com/openai/hanno",
                },
            )
            assert repo["workspace_id"] == workspace["id"]

            task = await _call(
                session,
                "hanno_create_task",
                {
                    "workspace_id": workspace["id"],
                    "title": "PR #42",
                    "workspace_repo_ids": [repo["id"]],
                },
            )
            assert task["workspace_id"] == workspace["id"]

            repos = await _call(session, "hanno_list_task_repos", {"task_id": task["id"]})
            assert len(repos) == 1


class TestRunTools:
    @pytest.mark.asyncio
    async def test_create_run(self):
        async with create_connected_server_and_client_session(mcp) as session:
            workspace = await _call(session, "hanno_create_workspace", {"title": "Alpha"})
            task = await _call(
                session,
                "hanno_create_task",
                {"workspace_id": workspace["id"], "title": "PR #42"},
            )
            result = await _call(
                session,
                "hanno_create_run",
                {
                    "run_type": "deploy",
                    "workspace_id": workspace["id"],
                    "task_id": task["id"],
                },
            )
            assert result["run_type"] == "deploy"
            assert result["workspace_id"] == workspace["id"]
            assert result["task_id"] == task["id"]

    @pytest.mark.asyncio
    async def test_list_runs_filter_by_task(self):
        async with create_connected_server_and_client_session(mcp) as session:
            workspace = await _call(session, "hanno_create_workspace", {"title": "Alpha"})
            task = await _call(
                session,
                "hanno_create_task",
                {"workspace_id": workspace["id"], "title": "PR #42"},
            )
            await _call(
                session,
                "hanno_create_run",
                {"run_type": "deploy", "workspace_id": workspace["id"], "task_id": task["id"]},
            )
            await _call(
                session,
                "hanno_create_run",
                {"run_type": "build", "workspace_id": workspace["id"]},
            )
            result = await _call(session, "hanno_list_runs", {"task_id": task["id"]})
            assert len(result) == 1
            assert result[0]["task_id"] == task["id"]


class TestFlowTools:
    @pytest.mark.asyncio
    async def test_step_event_artifact_approval_flow(self):
        async with create_connected_server_and_client_session(mcp) as session:
            workspace = await _call(session, "hanno_create_workspace", {"title": "Alpha"})
            run = await _call(
                session,
                "hanno_create_run",
                {"run_type": "deploy", "workspace_id": workspace["id"]},
            )
            run = await _call(session, "hanno_start_run", {"run_id": run["id"]})
            assert run["status"] == "running"

            step = await _call(
                session,
                "hanno_add_step",
                {"run_id": run["id"], "step_name": "build"},
            )
            await _call(session, "hanno_start_step", {"step_run_id": step["id"]})
            step = await _call(
                session,
                "hanno_complete_step",
                {"step_run_id": step["id"], "summary": "done"},
            )
            assert step["status"] == "succeeded"

            note = await _call(
                session,
                "hanno_add_note",
                {"run_id": run["id"], "message": "build done"},
            )
            assert note["kind"] == "note"

            artifact = await _call(
                session,
                "hanno_attach_artifact",
                {
                    "run_id": run["id"],
                    "data_base64": base64.b64encode(b"log").decode(),
                    "kind": "log",
                    "name": "build.log",
                    "content_type": "text/plain",
                },
            )
            assert artifact["name"] == "build.log"

            approval = await _call(
                session,
                "hanno_request_approval",
                {"run_id": run["id"], "authority": "github", "resource": "pr/1"},
            )
            approval = await _call(
                session,
                "hanno_grant_approval",
                {"approval_id": approval["id"]},
            )
            assert approval["status"] == "granted"

            events = await _call(session, "hanno_list_events", {"run_id": run["id"]})
            assert len(events) >= 4


class TestTaskQueries:
    @pytest.mark.asyncio
    async def test_find_tasks_by_ref_and_list_runs(self):
        async with create_connected_server_and_client_session(mcp) as session:
            workspace = await _call(session, "hanno_create_workspace", {"title": "Alpha"})
            task = await _call(
                session,
                "hanno_create_task",
                {
                    "workspace_id": workspace["id"],
                    "title": "PR #42",
                    "external_refs": [
                        {
                            "system": "github",
                            "ref_type": "pr",
                            "ref_id": "openai/hanno#42",
                        }
                    ],
                },
            )
            await _call(
                session,
                "hanno_create_run",
                {"run_type": "deploy", "workspace_id": workspace["id"], "task_id": task["id"]},
            )
            found = await _call(
                session,
                "hanno_find_tasks_by_ref",
                {
                    "workspace_id": workspace["id"],
                    "system": "github",
                    "ref_type": "pr",
                    "ref_id": "openai/hanno#42",
                },
            )
            assert len(found) == 1

            runs = await _call(session, "hanno_list_task_runs", {"task_id": task["id"]})
            assert len(runs) == 1
