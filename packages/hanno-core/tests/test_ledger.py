"""Tests for the RunLedger engine."""

from pathlib import Path

import pytest
from hanno_core.backends.sqlite.storage import SqliteStorageBackend
from hanno_core.engine.ledger import InvalidTransitionError, LedgerError, RunLedger
from hanno_core.models import (
    ApprovalStatus,
    ExternalRef,
    RunStatus,
    StepRunStatus,
    TaskStatus,
    WorkspaceStatus,
)
from hanno_core.models.identity import ActorRef
from hanno_core.stores.local_fs import LocalFsArtifactStore


@pytest.fixture
async def ledger(tmp_path: Path):
    storage = SqliteStorageBackend(":memory:")
    artifacts = LocalFsArtifactStore(tmp_path / "artifacts")
    await storage.initialize()
    yield RunLedger(storage, artifacts)
    await storage.close()


@pytest.fixture
def actor():
    return ActorRef(provider="test", identifier="agent")


@pytest.fixture
async def workspace(ledger):
    return await ledger.create_workspace(title="Alpha workspace")


@pytest.fixture
async def repo(ledger, workspace):
    return await ledger.create_workspace_repo(
        workspace.id,
        display_name="hanno",
        canonical_remote="github.com/openai/hanno",
        local_path="/tmp/hanno",
    )


@pytest.fixture
async def task(ledger, workspace, repo):
    return await ledger.create_task(
        workspace.id,
        title="PR #42",
        external_refs=[
            ExternalRef(system="github", ref_type="pr", ref_id="openai/hanno#42")
        ],
        workspace_repo_ids=[repo.id],
    )


class TestWorkspaceLifecycle:
    async def test_create_and_archive_workspace(self, ledger):
        workspace = await ledger.create_workspace(title="Alpha")
        assert workspace.status == WorkspaceStatus.ACTIVE

        archived = await ledger.archive_workspace(workspace.id)
        assert archived.status == WorkspaceStatus.ARCHIVED

    async def test_find_workspace_by_external_ref(self, ledger):
        await ledger.create_workspace(
            title="Alpha",
            external_refs=[ExternalRef(system="github", ref_type="org", ref_id="openai")],
        )
        found = await ledger.find_workspaces_by_external_ref(
            system="github",
            ref_type="org",
            ref_id="openai",
        )
        assert len(found) == 1


class TestTaskLifecycle:
    async def test_create_and_close_task(self, ledger, workspace):
        task = await ledger.create_task(workspace.id, title="Fix review")
        assert task.status == TaskStatus.ACTIVE

        task = await ledger.close_task(task.id)
        assert task.status == TaskStatus.CLOSED

    async def test_archive_task(self, ledger, workspace):
        task = await ledger.create_task(workspace.id)
        task = await ledger.archive_task(task.id)
        assert task.status == TaskStatus.ARCHIVED

    async def test_find_task_by_external_ref(self, ledger, workspace):
        task = await ledger.create_task(
            workspace.id,
            external_refs=[ExternalRef(system="github", ref_type="pr", ref_id="org/repo#42")],
        )
        found = await ledger.find_tasks_by_external_ref(
            workspace_id=workspace.id,
            system="github",
            ref_type="pr",
            ref_id="org/repo#42",
        )
        assert [item.id for item in found] == [task.id]

    async def test_task_repo_linking(self, ledger, workspace, repo):
        task = await ledger.create_task(workspace.id, title="Repo work")
        link = await ledger.link_task_repo(task.id, repo.id)
        assert link.task_id == task.id
        repos = await ledger.list_task_repos(task.id)
        assert [item.id for item in repos] == [repo.id]


class TestRunLifecycle:
    async def test_create_run_requires_workspace(self, ledger, actor):
        with pytest.raises(LedgerError, match="Workspace not found"):
            await ledger.create_run("test", actor=actor, workspace_id="missing")

    async def test_create_run_with_workspace_and_task(self, ledger, actor, workspace, task, repo):
        run = await ledger.create_run(
            "test",
            actor=actor,
            workspace_id=workspace.id,
            task_id=task.id,
            workspace_repo_id=repo.id,
            title="My Run",
        )
        assert run.workspace_id == workspace.id
        assert run.task_id == task.id
        assert run.workspace_repo_id == repo.id

    async def test_create_run_rejects_task_workspace_mismatch(
        self,
        ledger,
        actor,
        workspace,
        task,
    ):
        other = await ledger.create_workspace(title="Other")
        with pytest.raises(LedgerError, match="Task does not belong"):
            await ledger.create_run(
                "test",
                actor=actor,
                workspace_id=other.id,
                task_id=task.id,
            )

    async def test_list_runs_with_filters(self, ledger, actor, workspace, task, repo):
        await ledger.create_run(
            "test",
            actor=actor,
            workspace_id=workspace.id,
            task_id=task.id,
            workspace_repo_id=repo.id,
            labels={"env": "prod"},
        )
        await ledger.create_run("other", actor=actor, workspace_id=workspace.id)
        runs = await ledger.list_runs(
            workspace_id=workspace.id,
            task_id=task.id,
            workspace_repo_id=repo.id,
            labels={"env": "prod"},
        )
        assert len(runs) == 1

    async def test_full_lifecycle(self, ledger, actor, workspace):
        run = await ledger.create_run("test", actor=actor, workspace_id=workspace.id)
        run = await ledger.start_run(run.id, actor=actor)
        assert run.status == RunStatus.RUNNING
        run = await ledger.complete_run(run.id, actor=actor)
        assert run.status == RunStatus.SUCCEEDED

    async def test_waiting_and_resume(self, ledger, actor, workspace):
        run = await ledger.create_run("test", actor=actor, workspace_id=workspace.id)
        run = await ledger.start_run(run.id, actor=actor)
        run = await ledger.set_run_waiting(run.id, actor=actor)
        assert run.status == RunStatus.WAITING_HUMAN
        run = await ledger.resume_run(run.id, actor=actor)
        assert run.status == RunStatus.RUNNING

    async def test_invalid_transition(self, ledger, actor, workspace):
        run = await ledger.create_run("test", actor=actor, workspace_id=workspace.id)
        run = await ledger.start_run(run.id, actor=actor)
        run = await ledger.complete_run(run.id, actor=actor)
        with pytest.raises(InvalidTransitionError):
            await ledger.start_run(run.id, actor=actor)


class TestStepLifecycle:
    async def test_add_and_complete_step(self, ledger, actor, workspace):
        run = await ledger.create_run("test", actor=actor, workspace_id=workspace.id)
        step = await ledger.add_step(run.id, step_name="build", actor=actor)
        assert step.status == StepRunStatus.QUEUED

        await ledger.start_step(step.id, actor=actor)
        step = await ledger.complete_step(step.id, actor=actor, summary="done")
        assert step.status == StepRunStatus.SUCCEEDED


class TestArtifacts:
    async def test_attach_and_list(self, ledger, actor, workspace):
        run = await ledger.create_run("test", actor=actor, workspace_id=workspace.id)
        art = await ledger.attach_artifact(
            run.id,
            data=b"log content",
            kind="log",
            actor=actor,
            name="build.log",
        )
        assert art.name == "build.log"
        assert len(await ledger.list_artifacts(run.id)) == 1


class TestApprovals:
    async def test_request_and_grant(self, ledger, actor, workspace):
        run = await ledger.create_run("test", actor=actor, workspace_id=workspace.id)
        approval = await ledger.request_approval(run.id, actor=actor)
        approval = await ledger.grant_approval(approval.id, actor=actor)
        assert approval.status == ApprovalStatus.GRANTED


class TestLeases:
    async def test_acquire_and_release(self, ledger, actor, workspace):
        run = await ledger.create_run("test", actor=actor, workspace_id=workspace.id)
        lease = await ledger.acquire_lease(run.id, actor=actor)
        assert len(await ledger.list_active_leases(run.id)) == 1
        await ledger.release_lease(lease.id, actor=actor)
        assert len(await ledger.list_active_leases(run.id)) == 0
