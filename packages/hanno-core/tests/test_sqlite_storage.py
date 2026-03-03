"""Tests for the SQLite storage backend."""

from datetime import UTC, datetime, timedelta

import pytest
from hanno_core.backends.sqlite.storage import SqliteStorageBackend
from hanno_core.models import (
    Approval,
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
)
from hanno_core.models.identity import ActorRef


@pytest.fixture
async def storage():
    s = SqliteStorageBackend(":memory:")
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
def actor():
    return ActorRef(provider="test", identifier="agent")


@pytest.fixture
async def sample_run(storage, actor):
    run = Run(run_type="test_workflow", title="Test Run")
    return await storage.create_run(run)


class TestRunCRUD:
    async def test_create_and_get(self, storage, actor):
        run = Run(run_type="test", title="My Run")
        created = await storage.create_run(run)
        assert created.id == run.id

        fetched = await storage.get_run(run.id)
        assert fetched is not None
        assert fetched.run_type == "test"
        assert fetched.title == "My Run"
        assert fetched.status == RunStatus.PLANNED

    async def test_get_nonexistent(self, storage):
        result = await storage.get_run("nonexistent")
        assert result is None

    async def test_list_runs(self, storage):
        await storage.create_run(Run(run_type="a", title="Run A"))
        await storage.create_run(Run(run_type="b", title="Run B"))
        runs = await storage.list_runs()
        assert len(runs) == 2

    async def test_list_runs_filter_status(self, storage):
        r1 = Run(run_type="a", status=RunStatus.PLANNED)
        r2 = Run(run_type="b", status=RunStatus.RUNNING)
        await storage.create_run(r1)
        await storage.create_run(r2)

        planned = await storage.list_runs(status=RunStatus.PLANNED)
        assert len(planned) == 1
        assert planned[0].status == RunStatus.PLANNED

    async def test_list_runs_filter_type(self, storage):
        await storage.create_run(Run(run_type="alpha"))
        await storage.create_run(Run(run_type="beta"))
        results = await storage.list_runs(run_type="alpha")
        assert len(results) == 1

    async def test_update_run(self, storage, sample_run):
        sample_run.status = RunStatus.RUNNING
        sample_run.title = "Updated"
        updated = await storage.update_run(sample_run)
        assert updated.status == RunStatus.RUNNING

        fetched = await storage.get_run(sample_run.id)
        assert fetched is not None
        assert fetched.title == "Updated"


class TestEventAppend:
    async def test_append_and_list(self, storage, sample_run, actor):
        e1 = Event(
            run_id=sample_run.id,
            sequence=1,
            kind=EventKind.RUN_CREATED,
            actor=actor,
        )
        e2 = Event(
            run_id=sample_run.id,
            sequence=2,
            kind=EventKind.RUN_STARTED,
            actor=actor,
        )
        await storage.append_event(e1)
        await storage.append_event(e2)

        events = await storage.list_events(sample_run.id)
        assert len(events) == 2
        assert events[0].sequence == 1
        assert events[1].sequence == 2

    async def test_sequence_uniqueness(self, storage, sample_run, actor):
        e1 = Event(
            run_id=sample_run.id,
            sequence=1,
            kind=EventKind.RUN_CREATED,
            actor=actor,
        )
        await storage.append_event(e1)

        e2 = Event(
            run_id=sample_run.id,
            sequence=1,  # duplicate!
            kind=EventKind.RUN_STARTED,
            actor=actor,
        )
        with pytest.raises(
            Exception, match="UNIQUE constraint failed"
        ):
            await storage.append_event(e2)

    async def test_list_events_after_sequence(self, storage, sample_run, actor):
        for i in range(1, 6):
            await storage.append_event(
                Event(
                    run_id=sample_run.id,
                    sequence=i,
                    kind=EventKind.NOTE,
                    actor=actor,
                )
            )
        events = await storage.list_events(sample_run.id, after_sequence=3)
        assert len(events) == 2
        assert events[0].sequence == 4

    async def test_list_events_filter_kind(self, storage, sample_run, actor):
        await storage.append_event(
            Event(
                run_id=sample_run.id,
                sequence=1,
                kind=EventKind.RUN_CREATED,
                actor=actor,
            )
        )
        await storage.append_event(
            Event(
                run_id=sample_run.id,
                sequence=2,
                kind=EventKind.NOTE,
                actor=actor,
            )
        )
        events = await storage.list_events(
            sample_run.id, kinds=[EventKind.NOTE]
        )
        assert len(events) == 1
        assert events[0].kind == EventKind.NOTE

    async def test_get_event(self, storage, sample_run, actor):
        e = Event(
            run_id=sample_run.id,
            sequence=1,
            kind=EventKind.RUN_CREATED,
            actor=actor,
        )
        await storage.append_event(e)
        fetched = await storage.get_event(e.id)
        assert fetched is not None
        assert fetched.id == e.id


class TestStepRunCRUD:
    async def test_create_and_get(self, storage, sample_run):
        step = StepRun(run_id=sample_run.id, step_name="build")
        created = await storage.create_step_run(step)
        assert created.id == step.id

        fetched = await storage.get_step_run(step.id)
        assert fetched is not None
        assert fetched.step_name == "build"

    async def test_list_step_runs(self, storage, sample_run):
        await storage.create_step_run(
            StepRun(run_id=sample_run.id, step_name="build")
        )
        await storage.create_step_run(
            StepRun(run_id=sample_run.id, step_name="test")
        )
        steps = await storage.list_step_runs(sample_run.id)
        assert len(steps) == 2

    async def test_update_step_run(self, storage, sample_run):
        step = StepRun(run_id=sample_run.id, step_name="build")
        await storage.create_step_run(step)

        from hanno_core.models import StepRunStatus

        step.status = StepRunStatus.RUNNING
        step.started_at = datetime.now(UTC)
        await storage.update_step_run(step)

        fetched = await storage.get_step_run(step.id)
        assert fetched is not None
        assert fetched.status == StepRunStatus.RUNNING


class TestEdges:
    async def test_create_and_list(self, storage, sample_run):
        s1 = StepRun(run_id=sample_run.id, step_name="a")
        s2 = StepRun(run_id=sample_run.id, step_name="b")
        await storage.create_step_run(s1)
        await storage.create_step_run(s2)

        edge = Edge(
            run_id=sample_run.id,
            from_step_run_id=s1.id,
            to_step_run_id=s2.id,
            kind=EdgeKind.DEPENDS_ON,
        )
        await storage.create_edge(edge)

        edges = await storage.list_edges(sample_run.id)
        assert len(edges) == 1
        assert edges[0].kind == EdgeKind.DEPENDS_ON


class TestStateVersions:
    async def test_append_and_get_latest(self, storage, sample_run, actor):
        sv1 = StateVersion(
            run_id=sample_run.id,
            sequence=1,
            state_ref="sha256:aaa",
            state_hash="aaa",
            actor=actor,
        )
        await storage.append_state_version(sv1)

        sv2 = StateVersion(
            run_id=sample_run.id,
            sequence=2,
            prev_state_version_id=sv1.id,
            state_ref="sha256:bbb",
            state_hash="bbb",
            actor=actor,
        )
        await storage.append_state_version(sv2)

        latest = await storage.get_latest_state_version(sample_run.id)
        assert latest is not None
        assert latest.sequence == 2
        assert latest.prev_state_version_id == sv1.id


class TestArtifacts:
    async def test_create_and_list(self, storage, sample_run):
        art = Artifact(
            run_id=sample_run.id,
            kind="transcript",
            uri="sha256:abc",
            content_hash="sha256:abc",
            size=100,
        )
        await storage.create_artifact(art)

        artifacts = await storage.list_artifacts(sample_run.id)
        assert len(artifacts) == 1
        assert artifacts[0].kind == "transcript"


class TestApprovals:
    async def test_create_and_resolve(self, storage, sample_run, actor):
        approval = Approval(
            run_id=sample_run.id,
            authority="github",
            resource="pr/1",
            requested_by=actor,
        )
        await storage.create_approval(approval)

        fetched = await storage.get_approval(approval.id)
        assert fetched is not None
        assert fetched.status.value == "pending"

        fetched.status = approval.status.GRANTED
        fetched.resolved_by = actor
        fetched.resolved_at = datetime.now(UTC)
        await storage.update_approval(fetched)

        updated = await storage.get_approval(approval.id)
        assert updated is not None
        assert updated.status.value == "granted"


class TestLeases:
    async def test_create_and_list(self, storage, sample_run, actor):
        lease = Lease(
            run_id=sample_run.id,
            owner=actor,
            purpose="editing",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await storage.create_lease(lease)

        leases = await storage.list_active_leases(sample_run.id)
        assert len(leases) == 1

    async def test_delete_lease(self, storage, sample_run, actor):
        lease = Lease(
            run_id=sample_run.id,
            owner=actor,
            purpose="editing",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await storage.create_lease(lease)
        await storage.delete_lease(lease.id)

        result = await storage.get_lease(lease.id)
        assert result is None


class TestSequenceCounter:
    async def test_monotonic(self, storage, sample_run):
        s1 = await storage.next_sequence(sample_run.id)
        s2 = await storage.next_sequence(sample_run.id)
        s3 = await storage.next_sequence(sample_run.id)
        assert s1 == 1
        assert s2 == 2
        assert s3 == 3
