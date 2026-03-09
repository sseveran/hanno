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
    """Use a temp database for each test."""
    db_path = str(tmp_path / "test.db")
    art_path = str(tmp_path / "artifacts")
    with patch.dict(
        os.environ,
        {"HANNO_DB_PATH": db_path, "HANNO_ARTIFACT_PATH": art_path},
    ):
        yield


async def _call(session, name: str, args: dict | None = None) -> dict | list:
    """Call an MCP tool and parse the JSON result."""
    result = await session.call_tool(name, args or {})
    text = result.content[0].text
    return json.loads(text)


class TestRunTools:
    @pytest.mark.asyncio
    async def test_create_run(self):
        async with create_connected_server_and_client_session(mcp) as session:
            result = await _call(session, "hanno_create_run", {"run_type": "deploy"})
            assert result["run_type"] == "deploy"
            assert result["status"] == "planned"
            assert "id" in result

    @pytest.mark.asyncio
    async def test_create_run_with_options(self):
        async with create_connected_server_and_client_session(mcp) as session:
            result = await _call(
                session,
                "hanno_create_run",
                {
                    "run_type": "build",
                    "title": "My Build",
                    "labels": {"env": "staging"},
                    "external_refs": [
                        {"system": "github", "ref_type": "issue", "ref_id": "org/repo#1"},
                    ],
                },
            )
            assert result["title"] == "My Build"
            assert result["labels"] == {"env": "staging"}
            assert len(result["external_refs"]) == 1
            assert result["external_refs"][0]["system"] == "github"

    @pytest.mark.asyncio
    async def test_list_runs_empty(self):
        async with create_connected_server_and_client_session(mcp) as session:
            result = await _call(session, "hanno_list_runs")
            assert result == []

    @pytest.mark.asyncio
    async def test_list_runs(self):
        async with create_connected_server_and_client_session(mcp) as session:
            await _call(session, "hanno_create_run", {"run_type": "deploy"})
            await _call(session, "hanno_create_run", {"run_type": "build"})
            result = await _call(session, "hanno_list_runs")
            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_list_runs_filter_by_type(self):
        async with create_connected_server_and_client_session(mcp) as session:
            await _call(session, "hanno_create_run", {"run_type": "deploy"})
            await _call(session, "hanno_create_run", {"run_type": "build"})
            result = await _call(session, "hanno_list_runs", {"run_type": "deploy"})
            assert len(result) == 1
            assert result[0]["run_type"] == "deploy"

    @pytest.mark.asyncio
    async def test_get_run(self):
        async with create_connected_server_and_client_session(mcp) as session:
            created = await _call(session, "hanno_create_run", {"run_type": "deploy"})
            result = await _call(session, "hanno_get_run", {"run_id": created["id"]})
            assert result["id"] == created["id"]

    @pytest.mark.asyncio
    async def test_get_run_not_found(self):
        async with create_connected_server_and_client_session(mcp) as session:
            result = await _call(session, "hanno_get_run", {"run_id": "nonexistent"})
            assert "error" in result

    @pytest.mark.asyncio
    async def test_start_run(self):
        async with create_connected_server_and_client_session(mcp) as session:
            created = await _call(session, "hanno_create_run", {"run_type": "deploy"})
            result = await _call(session, "hanno_start_run", {"run_id": created["id"]})
            assert result["status"] == "running"

    @pytest.mark.asyncio
    async def test_complete_run(self):
        async with create_connected_server_and_client_session(mcp) as session:
            created = await _call(session, "hanno_create_run", {"run_type": "deploy"})
            await _call(session, "hanno_start_run", {"run_id": created["id"]})
            result = await _call(
                session, "hanno_complete_run", {"run_id": created["id"]}
            )
            assert result["status"] == "succeeded"

    @pytest.mark.asyncio
    async def test_fail_run(self):
        async with create_connected_server_and_client_session(mcp) as session:
            created = await _call(session, "hanno_create_run", {"run_type": "deploy"})
            await _call(session, "hanno_start_run", {"run_id": created["id"]})
            result = await _call(
                session,
                "hanno_fail_run",
                {"run_id": created["id"], "error": "disk full"},
            )
            assert result["status"] == "failed"

    @pytest.mark.asyncio
    async def test_cancel_run(self):
        async with create_connected_server_and_client_session(mcp) as session:
            created = await _call(session, "hanno_create_run", {"run_type": "deploy"})
            result = await _call(
                session,
                "hanno_cancel_run",
                {"run_id": created["id"], "reason": "changed mind"},
            )
            assert result["status"] == "canceled"


class TestStepTools:
    @pytest.mark.asyncio
    async def test_add_and_list_steps(self):
        async with create_connected_server_and_client_session(mcp) as session:
            run = await _call(session, "hanno_create_run", {"run_type": "deploy"})
            step = await _call(
                session,
                "hanno_add_step",
                {"run_id": run["id"], "step_name": "build"},
            )
            assert step["step_name"] == "build"
            assert step["status"] == "queued"

            steps = await _call(session, "hanno_list_steps", {"run_id": run["id"]})
            assert len(steps) == 1
            assert steps[0]["id"] == step["id"]

    @pytest.mark.asyncio
    async def test_step_lifecycle(self):
        async with create_connected_server_and_client_session(mcp) as session:
            run = await _call(session, "hanno_create_run", {"run_type": "deploy"})
            step = await _call(
                session,
                "hanno_add_step",
                {"run_id": run["id"], "step_name": "build"},
            )

            started = await _call(
                session, "hanno_start_step", {"step_run_id": step["id"]}
            )
            assert started["status"] == "running"

            completed = await _call(
                session,
                "hanno_complete_step",
                {"step_run_id": step["id"], "summary": "built OK"},
            )
            assert completed["status"] == "succeeded"

    @pytest.mark.asyncio
    async def test_fail_step(self):
        async with create_connected_server_and_client_session(mcp) as session:
            run = await _call(session, "hanno_create_run", {"run_type": "deploy"})
            step = await _call(
                session,
                "hanno_add_step",
                {"run_id": run["id"], "step_name": "test"},
            )
            await _call(session, "hanno_start_step", {"step_run_id": step["id"]})
            failed = await _call(
                session,
                "hanno_fail_step",
                {"step_run_id": step["id"], "error": "tests failed"},
            )
            assert failed["status"] == "failed"


class TestEventTools:
    @pytest.mark.asyncio
    async def test_list_events(self):
        async with create_connected_server_and_client_session(mcp) as session:
            run = await _call(session, "hanno_create_run", {"run_type": "deploy"})
            events = await _call(session, "hanno_list_events", {"run_id": run["id"]})
            assert len(events) >= 1  # at least the run_created event

    @pytest.mark.asyncio
    async def test_add_note(self):
        async with create_connected_server_and_client_session(mcp) as session:
            run = await _call(session, "hanno_create_run", {"run_type": "deploy"})
            note = await _call(
                session,
                "hanno_add_note",
                {"run_id": run["id"], "message": "Starting deploy"},
            )
            assert note["kind"] == "note"
            assert note["payload"]["message"] == "Starting deploy"

    @pytest.mark.asyncio
    async def test_list_events_after_sequence(self):
        async with create_connected_server_and_client_session(mcp) as session:
            run = await _call(session, "hanno_create_run", {"run_type": "deploy"})
            await _call(
                session,
                "hanno_add_note",
                {"run_id": run["id"], "message": "note 1"},
            )
            await _call(
                session,
                "hanno_add_note",
                {"run_id": run["id"], "message": "note 2"},
            )
            # Get events after the first one
            events = await _call(
                session,
                "hanno_list_events",
                {"run_id": run["id"], "after_sequence": 1},
            )
            assert len(events) >= 2  # at least the two notes


class TestArtifactTools:
    @pytest.mark.asyncio
    async def test_attach_and_list_artifacts(self):
        async with create_connected_server_and_client_session(mcp) as session:
            run = await _call(session, "hanno_create_run", {"run_type": "deploy"})
            data = base64.b64encode(b"hello world").decode()
            artifact = await _call(
                session,
                "hanno_attach_artifact",
                {
                    "run_id": run["id"],
                    "data_base64": data,
                    "kind": "log",
                    "name": "build.log",
                    "content_type": "text/plain",
                },
            )
            assert artifact["kind"] == "log"
            assert artifact["name"] == "build.log"
            assert artifact["size"] == 11  # len(b"hello world")

            artifacts = await _call(
                session, "hanno_list_artifacts", {"run_id": run["id"]}
            )
            assert len(artifacts) == 1
            assert artifacts[0]["id"] == artifact["id"]


class TestApprovalTools:
    @pytest.mark.asyncio
    async def test_request_and_grant_approval(self):
        async with create_connected_server_and_client_session(mcp) as session:
            run = await _call(session, "hanno_create_run", {"run_type": "deploy"})
            approval = await _call(
                session,
                "hanno_request_approval",
                {
                    "run_id": run["id"],
                    "authority": "team-lead",
                    "resource": "prod-deploy",
                },
            )
            assert approval["status"] == "pending"
            assert approval["authority"] == "team-lead"

            granted = await _call(
                session,
                "hanno_grant_approval",
                {"approval_id": approval["id"]},
            )
            assert granted["status"] == "granted"

    @pytest.mark.asyncio
    async def test_deny_approval(self):
        async with create_connected_server_and_client_session(mcp) as session:
            run = await _call(session, "hanno_create_run", {"run_type": "deploy"})
            approval = await _call(
                session,
                "hanno_request_approval",
                {"run_id": run["id"], "authority": "security"},
            )
            denied = await _call(
                session,
                "hanno_deny_approval",
                {"approval_id": approval["id"], "reason": "not ready"},
            )
            assert denied["status"] == "denied"

    @pytest.mark.asyncio
    async def test_list_approvals(self):
        async with create_connected_server_and_client_session(mcp) as session:
            run = await _call(session, "hanno_create_run", {"run_type": "deploy"})
            await _call(
                session,
                "hanno_request_approval",
                {"run_id": run["id"], "authority": "team-lead"},
            )
            await _call(
                session,
                "hanno_request_approval",
                {"run_id": run["id"], "authority": "security"},
            )
            approvals = await _call(
                session, "hanno_list_approvals", {"run_id": run["id"]}
            )
            assert len(approvals) == 2

    @pytest.mark.asyncio
    async def test_list_pending_approvals(self):
        async with create_connected_server_and_client_session(mcp) as session:
            run = await _call(session, "hanno_create_run", {"run_type": "deploy"})
            a1 = await _call(
                session,
                "hanno_request_approval",
                {"run_id": run["id"], "authority": "team-lead"},
            )
            await _call(
                session,
                "hanno_request_approval",
                {"run_id": run["id"], "authority": "security"},
            )
            await _call(
                session, "hanno_grant_approval", {"approval_id": a1["id"]}
            )
            pending = await _call(
                session,
                "hanno_list_approvals",
                {"run_id": run["id"], "pending_only": True},
            )
            assert len(pending) == 1
            assert pending[0]["authority"] == "security"


class TestSessionTools:
    @pytest.mark.asyncio
    async def test_create_session(self):
        async with create_connected_server_and_client_session(mcp) as session:
            result = await _call(session, "hanno_create_session", {
                "title": "PR #42 Work",
            })
            assert result["title"] == "PR #42 Work"
            assert result["status"] == "active"
            assert "id" in result

    @pytest.mark.asyncio
    async def test_create_session_with_refs(self):
        async with create_connected_server_and_client_session(mcp) as session:
            result = await _call(session, "hanno_create_session", {
                "title": "PR Work",
                "external_refs": [
                    {"system": "github", "ref_type": "pr", "ref_id": "org/repo#42"},
                ],
            })
            assert len(result["external_refs"]) == 1

    @pytest.mark.asyncio
    async def test_get_session(self):
        async with create_connected_server_and_client_session(mcp) as session:
            created = await _call(session, "hanno_create_session", {
                "title": "Test",
            })
            result = await _call(session, "hanno_get_session", {
                "session_id": created["id"],
            })
            assert result["id"] == created["id"]

    @pytest.mark.asyncio
    async def test_get_session_not_found(self):
        async with create_connected_server_and_client_session(mcp) as session:
            result = await _call(session, "hanno_get_session", {
                "session_id": "nonexistent",
            })
            assert "error" in result

    @pytest.mark.asyncio
    async def test_list_sessions(self):
        async with create_connected_server_and_client_session(mcp) as session:
            await _call(session, "hanno_create_session", {"title": "A"})
            await _call(session, "hanno_create_session", {"title": "B"})
            result = await _call(session, "hanno_list_sessions")
            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_close_session(self):
        async with create_connected_server_and_client_session(mcp) as session:
            created = await _call(session, "hanno_create_session", {
                "title": "Test",
            })
            result = await _call(session, "hanno_close_session", {
                "session_id": created["id"],
            })
            assert result["status"] == "closed"

    @pytest.mark.asyncio
    async def test_find_session_by_ref(self):
        async with create_connected_server_and_client_session(mcp) as session:
            await _call(session, "hanno_create_session", {
                "title": "PR #42",
                "external_refs": [
                    {"system": "github", "ref_type": "pr", "ref_id": "org/repo#42"},
                ],
            })
            result = await _call(session, "hanno_find_session_by_ref", {
                "system": "github",
                "ref_type": "pr",
                "ref_id": "org/repo#42",
            })
            assert len(result) == 1
            assert result[0]["title"] == "PR #42"

    @pytest.mark.asyncio
    async def test_list_session_runs(self):
        async with create_connected_server_and_client_session(mcp) as session:
            s = await _call(session, "hanno_create_session", {"title": "Test"})
            await _call(session, "hanno_create_run", {
                "run_type": "test",
                "session_id": s["id"],
            })
            await _call(session, "hanno_create_run", {
                "run_type": "test",
                "session_id": s["id"],
            })
            result = await _call(session, "hanno_list_session_runs", {
                "session_id": s["id"],
            })
            assert len(result) == 2


class TestFullLifecycle:
    @pytest.mark.asyncio
    async def test_full_workflow(self):
        """Test a complete workflow: create → start → step → complete."""
        async with create_connected_server_and_client_session(mcp) as session:
            # Create and start a run
            run = await _call(session, "hanno_create_run", {
                "run_type": "deploy",
                "title": "Deploy v1.2",
            })
            run = await _call(session, "hanno_start_run", {"run_id": run["id"]})
            assert run["status"] == "running"

            # Add a step, start it, complete it
            step = await _call(session, "hanno_add_step", {
                "run_id": run["id"],
                "step_name": "build",
            })
            await _call(session, "hanno_start_step", {"step_run_id": step["id"]})
            await _call(session, "hanno_complete_step", {
                "step_run_id": step["id"],
                "summary": "Built successfully",
            })

            # Add a note
            await _call(session, "hanno_add_note", {
                "run_id": run["id"],
                "message": "All checks passed",
            })

            # Attach an artifact
            data = base64.b64encode(b"deployment log content").decode()
            await _call(session, "hanno_attach_artifact", {
                "run_id": run["id"],
                "data_base64": data,
                "kind": "log",
                "name": "deploy.log",
            })

            # Complete the run
            run = await _call(
                session, "hanno_complete_run", {"run_id": run["id"]}
            )
            assert run["status"] == "succeeded"

            # Verify events were recorded
            events = await _call(
                session, "hanno_list_events", {"run_id": run["id"]}
            )
            assert len(events) >= 6  # created, started, step events, note, artifact, completed

            # Verify steps
            steps = await _call(
                session, "hanno_list_steps", {"run_id": run["id"]}
            )
            assert len(steps) == 1
            assert steps[0]["status"] == "succeeded"
