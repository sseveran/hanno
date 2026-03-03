"""Tests for the RunLedger engine."""

from pathlib import Path

import pytest
from hanno_core.backends.sqlite.storage import SqliteStorageBackend
from hanno_core.engine.ledger import (
    InvalidTransitionError,
    LedgerError,
    RunLedger,
)
from hanno_core.models import (
    ApprovalStatus,
    EventKind,
    RunStatus,
    StepRunStatus,
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


class TestRunLifecycle:
    async def test_create_run(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor, title="My Run")
        assert run.status == RunStatus.PLANNED
        assert run.run_type == "test"
        assert run.title == "My Run"

    async def test_full_lifecycle(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        assert run.status == RunStatus.PLANNED

        run = await ledger.start_run(run.id, actor=actor)
        assert run.status == RunStatus.RUNNING

        run = await ledger.complete_run(run.id, actor=actor)
        assert run.status == RunStatus.SUCCEEDED

    async def test_fail_run(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        run = await ledger.start_run(run.id, actor=actor)
        run = await ledger.fail_run(run.id, actor=actor, error="oops")
        assert run.status == RunStatus.FAILED

    async def test_cancel_run(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        run = await ledger.cancel_run(run.id, actor=actor, reason="no longer needed")
        assert run.status == RunStatus.CANCELED

    async def test_waiting_and_resume(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        run = await ledger.start_run(run.id, actor=actor)
        run = await ledger.set_run_waiting(run.id, actor=actor)
        assert run.status == RunStatus.WAITING_HUMAN

        run = await ledger.resume_run(run.id, actor=actor)
        assert run.status == RunStatus.RUNNING

    async def test_blocked_and_resume(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        run = await ledger.start_run(run.id, actor=actor)
        run = await ledger.set_run_blocked(run.id, actor=actor)
        assert run.status == RunStatus.BLOCKED

        run = await ledger.resume_run(run.id, actor=actor)
        assert run.status == RunStatus.RUNNING

    async def test_invalid_transition(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        run = await ledger.start_run(run.id, actor=actor)
        run = await ledger.complete_run(run.id, actor=actor)

        with pytest.raises(InvalidTransitionError):
            await ledger.start_run(run.id, actor=actor)

    async def test_cannot_start_completed_run(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        run = await ledger.start_run(run.id, actor=actor)
        run = await ledger.complete_run(run.id, actor=actor)

        with pytest.raises(InvalidTransitionError, match="terminal"):
            await ledger.start_run(run.id, actor=actor)

    async def test_run_not_found(self, ledger, actor):
        with pytest.raises(LedgerError, match="not found"):
            await ledger.start_run("nonexistent", actor=actor)


class TestStepLifecycle:
    async def test_add_and_start_step(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        step = await ledger.add_step(
            run.id, step_name="build", actor=actor
        )
        assert step.status == StepRunStatus.QUEUED

        step = await ledger.start_step(step.id, actor=actor)
        assert step.status == StepRunStatus.RUNNING

    async def test_complete_step(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        step = await ledger.add_step(
            run.id, step_name="build", actor=actor
        )
        step = await ledger.start_step(step.id, actor=actor)
        step = await ledger.complete_step(
            step.id, actor=actor, summary="done", output={"image": "sha:abc"}
        )
        assert step.status == StepRunStatus.SUCCEEDED
        assert step.summary == "done"

    async def test_fail_step(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        step = await ledger.add_step(
            run.id, step_name="build", actor=actor
        )
        step = await ledger.start_step(step.id, actor=actor)
        step = await ledger.fail_step(
            step.id, actor=actor, error="compile failed"
        )
        assert step.status == StepRunStatus.FAILED

    async def test_skip_step(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        step = await ledger.add_step(
            run.id, step_name="optional", actor=actor
        )
        step = await ledger.skip_step(step.id, actor=actor)
        assert step.status == StepRunStatus.SKIPPED

    async def test_invalid_step_transition(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        step = await ledger.add_step(
            run.id, step_name="build", actor=actor
        )
        with pytest.raises(InvalidTransitionError):
            await ledger.complete_step(step.id, actor=actor)

    async def test_step_with_dependencies(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        s1 = await ledger.add_step(
            run.id, step_name="build", actor=actor
        )
        s2 = await ledger.add_step(
            run.id,
            step_name="test",
            actor=actor,
            depends_on=[s1.id],
        )

        edges = await ledger.list_edges(run.id)
        assert len(edges) == 1
        assert edges[0].from_step_run_id == s1.id
        assert edges[0].to_step_run_id == s2.id

    async def test_list_steps(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        await ledger.add_step(run.id, step_name="a", actor=actor)
        await ledger.add_step(run.id, step_name="b", actor=actor)
        steps = await ledger.list_steps(run.id)
        assert len(steps) == 2


class TestArtifacts:
    async def test_attach_and_list(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        art = await ledger.attach_artifact(
            run.id,
            data=b"log content",
            kind="log",
            actor=actor,
            name="build.log",
        )
        assert art.size == len(b"log content")
        assert art.name == "build.log"

        artifacts = await ledger.list_artifacts(run.id)
        assert len(artifacts) == 1


class TestApprovals:
    async def test_request_and_grant(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        approval = await ledger.request_approval(
            run.id,
            actor=actor,
            authority="github",
            resource="pr/1",
        )
        assert approval.status == ApprovalStatus.PENDING

        approval = await ledger.grant_approval(approval.id, actor=actor)
        assert approval.status == ApprovalStatus.GRANTED

    async def test_request_and_deny(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        approval = await ledger.request_approval(
            run.id, actor=actor
        )
        approval = await ledger.deny_approval(
            approval.id, actor=actor, reason="needs more work"
        )
        assert approval.status == ApprovalStatus.DENIED
        assert approval.reason == "needs more work"

    async def test_double_resolve(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        approval = await ledger.request_approval(
            run.id, actor=actor
        )
        await ledger.grant_approval(approval.id, actor=actor)
        with pytest.raises(InvalidTransitionError):
            await ledger.grant_approval(approval.id, actor=actor)


class TestLeases:
    async def test_acquire_and_release(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        lease = await ledger.acquire_lease(
            run.id, actor=actor, purpose="editing", ttl_seconds=60
        )
        assert lease.purpose == "editing"

        leases = await ledger.list_active_leases(run.id)
        assert len(leases) == 1

        await ledger.release_lease(lease.id, actor=actor)
        leases = await ledger.list_active_leases(run.id)
        assert len(leases) == 0


class TestEvents:
    async def test_events_recorded(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        await ledger.start_run(run.id, actor=actor)

        events = await ledger.list_events(run.id)
        assert len(events) == 2
        assert events[0].kind == EventKind.RUN_CREATED
        assert events[1].kind == EventKind.RUN_STARTED

    async def test_add_note(self, ledger, actor):
        run = await ledger.create_run("test", actor=actor)
        note = await ledger.add_note(
            run.id, actor=actor, message="This is a note"
        )
        assert note.kind == EventKind.NOTE
        assert note.payload["message"] == "This is a note"


class TestStateVersions:
    async def test_append_and_get(self, ledger, actor):
        import json

        run = await ledger.create_run("test", actor=actor)
        state_data = json.dumps({"pr": {"number": 42}}).encode()

        sv = await ledger.append_state_version(
            run.id, state_data=state_data, actor=actor
        )
        assert sv.run_id == run.id
        assert sv.state_ref.startswith("sha256:")

        latest = await ledger.get_latest_state(run.id)
        assert latest is not None
        assert latest.id == sv.id
