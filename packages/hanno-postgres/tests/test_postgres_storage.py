"""Tests for the Postgres storage backend."""

from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from hanno_core.models import (
    Approval,
    ApprovalStatus,
    Artifact,
    Edge,
    EdgeKind,
    Event,
    EventKind,
    Lease,
    Run,
    RunStatus,
    StateVersion,
    StepRun,
    StepRunStatus,
    Task,
    TaskRepoLink,
    TaskStatus,
    Workspace,
    WorkspaceRepo,
)
from hanno_core.models.identity import ActorRef


@pytest.fixture
def actor():
    return ActorRef(provider="test", identifier="agent")


@pytest.fixture
async def sample_workspace(storage):
    return await storage.create_workspace(Workspace(title="Main workspace"))


@pytest.fixture
async def sample_repo(storage, sample_workspace):
    return await storage.create_workspace_repo(
        WorkspaceRepo(
            workspace_id=sample_workspace.id,
            display_name="hanno",
            canonical_remote="github.com/openai/hanno",
            local_path="/tmp/hanno",
        )
    )


@pytest.fixture
async def sample_task(storage, sample_workspace):
    return await storage.create_task(Task(workspace_id=sample_workspace.id, title="PR #42"))


@pytest.fixture
async def sample_run(storage, sample_workspace, sample_task, sample_repo):
    return await storage.create_run(
        Run(
            workspace_id=sample_workspace.id,
            task_id=sample_task.id,
            workspace_repo_id=sample_repo.id,
            run_type="test_workflow",
            title="Test Run",
        )
    )


class TestWorkspaceCRUD:
    async def test_create_and_get(self, storage):
        workspace = Workspace(title="Alpha")
        await storage.create_workspace(workspace)
        fetched = await storage.get_workspace(workspace.id)
        assert fetched is not None
        assert fetched.title == "Alpha"

    async def test_find_by_external_ref(self, storage):
        workspace = Workspace(
            title="Alpha",
            external_refs=[
                {
                    "system": "github",
                    "ref_type": "org",
                    "ref_id": "openai",
                    "url": "https://github.com/openai",
                }
            ],
        )
        await storage.create_workspace(workspace)
        found = await storage.find_workspaces_by_external_ref(
            system="github",
            ref_type="org",
            ref_id="openai",
        )
        assert len(found) == 1


class TestWorkspaceRepoCRUD:
    async def test_create_and_list(self, storage, sample_workspace):
        repo = WorkspaceRepo(
            workspace_id=sample_workspace.id,
            display_name="hanno",
            canonical_remote="github.com/openai/hanno",
            local_path="/tmp/hanno",
        )
        await storage.create_workspace_repo(repo)
        repos = await storage.list_workspace_repos(sample_workspace.id)
        assert len(repos) == 1

    async def test_find_by_repo_context(self, storage, sample_repo):
        found = await storage.find_workspace_repos(
            canonical_remote="github.com/openai/hanno"
        )
        assert len(found) == 1
        assert found[0].id == sample_repo.id


class TestTaskCRUD:
    async def test_create_and_get(self, storage, sample_workspace):
        task = Task(workspace_id=sample_workspace.id, title="Fix review")
        await storage.create_task(task)
        fetched = await storage.get_task(task.id)
        assert fetched is not None
        assert fetched.workspace_id == sample_workspace.id

    async def test_list_by_workspace_and_status(self, storage, sample_workspace):
        await storage.create_task(Task(workspace_id=sample_workspace.id, title="A"))
        await storage.create_task(
            Task(workspace_id=sample_workspace.id, title="B", status=TaskStatus.CLOSED)
        )
        tasks = await storage.list_tasks(
            workspace_id=sample_workspace.id,
            status=TaskStatus.CLOSED,
        )
        assert len(tasks) == 1
        assert tasks[0].title == "B"

    async def test_find_by_external_ref(self, storage, sample_workspace):
        task = Task(
            workspace_id=sample_workspace.id,
            title="PR work",
            external_refs=[
                {
                    "system": "github",
                    "ref_type": "pr",
                    "ref_id": "org/repo#42",
                    "url": "https://github.com/org/repo/pull/42",
                }
            ],
        )
        await storage.create_task(task)
        found = await storage.find_tasks_by_external_ref(
            workspace_id=sample_workspace.id,
            system="github",
            ref_type="pr",
            ref_id="org/repo#42",
        )
        assert len(found) == 1


class TestTaskRepoLinks:
    async def test_create_and_list(self, storage, sample_task, sample_repo):
        await storage.create_task_repo_link(
            TaskRepoLink(task_id=sample_task.id, workspace_repo_id=sample_repo.id)
        )
        links = await storage.list_task_repo_links(sample_task.id)
        assert len(links) == 1
        assert await storage.has_task_repo_link(sample_task.id, sample_repo.id)


class TestRunCRUD:
    async def test_create_and_get(self, storage, sample_workspace):
        run = Run(workspace_id=sample_workspace.id, run_type="test", title="My Run")
        await storage.create_run(run)
        fetched = await storage.get_run(run.id)
        assert fetched is not None
        assert fetched.workspace_id == sample_workspace.id

    async def test_list_runs_filters(self, storage, sample_workspace, sample_task, sample_repo):
        await storage.create_run(
            Run(
                workspace_id=sample_workspace.id,
                task_id=sample_task.id,
                workspace_repo_id=sample_repo.id,
                run_type="alpha",
                labels={"env": "prod"},
            )
        )
        await storage.create_run(
            Run(workspace_id=sample_workspace.id, run_type="beta", labels={"env": "staging"})
        )
        runs = await storage.list_runs(
            workspace_id=sample_workspace.id,
            task_id=sample_task.id,
            workspace_repo_id=sample_repo.id,
            run_type="alpha",
            labels={"env": "prod"},
        )
        assert len(runs) == 1

    async def test_update_run(self, storage, sample_run):
        sample_run.status = RunStatus.RUNNING
        await storage.update_run(sample_run)
        fetched = await storage.get_run(sample_run.id)
        assert fetched is not None
        assert fetched.status == RunStatus.RUNNING


class TestEventAppend:
    async def test_append_and_list(self, storage, sample_run, actor):
        await storage.append_event(
            Event(run_id=sample_run.id, sequence=1, kind=EventKind.RUN_CREATED, actor=actor)
        )
        await storage.append_event(
            Event(run_id=sample_run.id, sequence=2, kind=EventKind.RUN_STARTED, actor=actor)
        )
        events = await storage.list_events(sample_run.id)
        assert [event.sequence for event in events] == [1, 2]

    async def test_sequence_uniqueness(self, storage, sample_run, actor):
        await storage.append_event(
            Event(run_id=sample_run.id, sequence=1, kind=EventKind.RUN_CREATED, actor=actor)
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await storage.append_event(
                Event(run_id=sample_run.id, sequence=1, kind=EventKind.RUN_STARTED, actor=actor)
            )


class TestStepRunCRUD:
    async def test_create_and_update(self, storage, sample_run):
        step = StepRun(run_id=sample_run.id, step_name="build")
        await storage.create_step_run(step)
        step.status = StepRunStatus.RUNNING
        step.started_at = datetime.now(UTC)
        await storage.update_step_run(step)
        fetched = await storage.get_step_run(step.id)
        assert fetched is not None
        assert fetched.status == StepRunStatus.RUNNING


class TestEdges:
    async def test_create_and_list(self, storage, sample_run):
        left = StepRun(run_id=sample_run.id, step_name="a")
        right = StepRun(run_id=sample_run.id, step_name="b")
        await storage.create_step_run(left)
        await storage.create_step_run(right)
        await storage.create_edge(
            Edge(
                run_id=sample_run.id,
                from_step_run_id=left.id,
                to_step_run_id=right.id,
                kind=EdgeKind.DEPENDS_ON,
            )
        )
        edges = await storage.list_edges(sample_run.id)
        assert len(edges) == 1


class TestStateVersions:
    async def test_append_and_get_latest(self, storage, sample_run, actor):
        await storage.append_state_version(
            StateVersion(
                run_id=sample_run.id,
                sequence=1,
                state_ref="sha256:aaa",
                state_hash="aaa",
                actor=actor,
            )
        )
        latest = await storage.get_latest_state_version(sample_run.id)
        assert latest is not None
        assert latest.sequence == 1


class TestArtifacts:
    async def test_create_and_list(self, storage, sample_run):
        await storage.create_artifact(
            Artifact(
                run_id=sample_run.id,
                kind="transcript",
                uri="sha256:abc",
                content_hash="sha256:abc",
                size=100,
            )
        )
        artifacts = await storage.list_artifacts(sample_run.id)
        assert len(artifacts) == 1


class TestApprovals:
    async def test_create_and_resolve(self, storage, sample_run, actor):
        approval = Approval(
            run_id=sample_run.id,
            authority="github",
            resource="pr/1",
            requested_by=actor,
        )
        await storage.create_approval(approval)
        approval.status = ApprovalStatus.GRANTED
        approval.resolved_by = actor
        approval.resolved_at = datetime.now(UTC)
        await storage.update_approval(approval)
        fetched = await storage.get_approval(approval.id)
        assert fetched is not None
        assert fetched.status == ApprovalStatus.GRANTED


class TestLeases:
    async def test_create_and_delete(self, storage, sample_run, actor):
        lease = Lease(
            run_id=sample_run.id,
            owner=actor,
            purpose="editing",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await storage.create_lease(lease)
        await storage.delete_lease(lease.id)
        assert await storage.get_lease(lease.id) is None


class TestSequenceCounter:
    async def test_monotonic(self, storage, sample_run):
        assert await storage.next_sequence(sample_run.id) == 1
        assert await storage.next_sequence(sample_run.id) == 2
