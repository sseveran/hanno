"""Tests for domain models."""

import json

from hanno_core.models import (
    ActorRef,
    Approval,
    ApprovalStatus,
    Artifact,
    Edge,
    EdgeKind,
    Event,
    EventKind,
    ExternalRef,
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
    WorkspaceStatus,
)


class TestActorRef:
    def test_json_roundtrip(self):
        actor = ActorRef(
            provider="github",
            identifier="steve",
            display_name="Steve",
            metadata={"email": "s@example.com"},
        )
        restored = ActorRef.model_validate_json(actor.model_dump_json())
        assert restored == actor


class TestExternalRef:
    def test_json_roundtrip(self):
        ref = ExternalRef(
            system="jira",
            ref_type="ticket",
            ref_id="PROJ-123",
            url="https://jira.example.com/PROJ-123",
        )
        restored = ExternalRef.model_validate(json.loads(ref.model_dump_json()))
        assert restored == ref


class TestWorkspace:
    def test_defaults(self):
        workspace = Workspace()
        assert workspace.status == WorkspaceStatus.ACTIVE
        assert workspace.external_refs == []
        assert workspace.labels == {}


class TestWorkspaceRepo:
    def test_defaults(self):
        repo = WorkspaceRepo(workspace_id="ws-1")
        assert repo.vcs == "git"
        assert repo.canonical_remote == ""
        assert repo.local_path is None


class TestTask:
    def test_defaults(self):
        task = Task(workspace_id="ws-1")
        assert task.status == TaskStatus.ACTIVE
        assert task.external_refs == []
        assert task.labels == {}


class TestTaskRepoLink:
    def test_create(self):
        link = TaskRepoLink(task_id="task-1", workspace_repo_id="repo-1")
        assert link.task_id == "task-1"
        assert link.workspace_repo_id == "repo-1"


class TestRun:
    def test_defaults(self):
        run = Run(workspace_id="ws-1", run_type="test")
        assert run.status == RunStatus.PLANNED
        assert run.title == ""
        assert run.task_id is None
        assert run.workspace_repo_id is None

    def test_json_roundtrip(self):
        run = Run(
            workspace_id="ws-1",
            task_id="task-1",
            workspace_repo_id="repo-1",
            run_type="pr_authoring",
            title="Fix bug",
            labels={"env": "staging"},
            external_refs=[
                ExternalRef(system="github", ref_type="pr", ref_id="org/repo#5")
            ],
        )
        restored = Run.model_validate(json.loads(run.model_dump_json()))
        assert restored.workspace_id == "ws-1"
        assert restored.task_id == "task-1"
        assert restored.workspace_repo_id == "repo-1"


class TestStepRun:
    def test_defaults(self):
        step = StepRun(run_id="run-1", step_name="build")
        assert step.status == StepRunStatus.QUEUED
        assert step.iteration == 0


class TestEvent:
    def test_create(self):
        event = Event(
            run_id="run-1",
            sequence=1,
            kind=EventKind.RUN_CREATED,
            actor=ActorRef(provider="test", identifier="agent"),
        )
        assert event.payload == {}


class TestEdge:
    def test_create(self):
        edge = Edge(
            run_id="run-1",
            from_step_run_id="step-1",
            to_step_run_id="step-2",
            kind=EdgeKind.DEPENDS_ON,
        )
        assert edge.kind == EdgeKind.DEPENDS_ON


class TestStateVersion:
    def test_create(self):
        sv = StateVersion(
            run_id="run-1",
            sequence=1,
            state_ref="sha256:abc",
            state_hash="abc",
            actor=ActorRef(provider="test", identifier="agent"),
        )
        assert sv.prev_state_version_id is None


class TestArtifact:
    def test_create(self):
        art = Artifact(
            run_id="run-1",
            kind="transcript",
            uri="sha256:abc",
            content_hash="sha256:abc",
            size=1024,
        )
        assert art.content_type == "application/octet-stream"


class TestApproval:
    def test_create(self):
        approval = Approval(
            run_id="run-1",
            requested_by=ActorRef(provider="test", identifier="agent"),
            authority="github",
            resource="https://github.com/org/repo/pull/1",
        )
        assert approval.status == ApprovalStatus.PENDING


class TestLease:
    def test_create(self):
        from datetime import UTC, datetime, timedelta

        lease = Lease(
            run_id="run-1",
            owner=ActorRef(provider="test", identifier="agent"),
            purpose="editing",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        assert lease.lease_token
