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
    Lease,
    Run,
    RunStatus,
    StateVersion,
    StepRun,
    StepRunStatus,
)


class TestActorRef:
    def test_create(self):
        actor = ActorRef(provider="github", identifier="steve")
        assert actor.provider == "github"
        assert actor.identifier == "steve"
        assert actor.display_name is None
        assert actor.metadata == {}

    def test_frozen(self):
        actor = ActorRef(provider="local", identifier="x")
        try:
            actor.provider = "other"  # type: ignore[misc]
            raise AssertionError("Should have raised")
        except Exception:
            pass

    def test_json_roundtrip(self):
        actor = ActorRef(
            provider="github",
            identifier="steve",
            display_name="Steve",
            metadata={"email": "s@example.com"},
        )
        data = actor.model_dump_json()
        restored = ActorRef.model_validate_json(data)
        assert restored == actor


class TestRun:
    def test_defaults(self):
        run = Run(run_type="test")
        assert run.status == RunStatus.PLANNED
        assert run.title == ""
        assert run.links == []
        assert run.labels == {}
        assert run.id  # ULID generated

    def test_json_roundtrip(self):
        run = Run(
            run_type="pr_authoring",
            title="Fix bug",
            labels={"env": "staging"},
        )
        data = json.loads(run.model_dump_json())
        assert data["run_type"] == "pr_authoring"
        assert data["status"] == "planned"
        restored = Run.model_validate(data)
        assert restored.run_type == "pr_authoring"


class TestStepRun:
    def test_defaults(self):
        step = StepRun(run_id="abc", step_name="build")
        assert step.status == StepRunStatus.QUEUED
        assert step.iteration == 0
        assert step.started_at is None

    def test_all_statuses(self):
        for s in StepRunStatus:
            step = StepRun(run_id="abc", step_name="x", status=s)
            assert step.status == s


class TestEvent:
    def test_create(self):
        actor = ActorRef(provider="test", identifier="agent")
        event = Event(
            run_id="r1",
            sequence=1,
            kind=EventKind.RUN_CREATED,
            actor=actor,
        )
        assert event.sequence == 1
        assert event.kind == EventKind.RUN_CREATED
        assert event.payload == {}


class TestEdge:
    def test_create(self):
        edge = Edge(
            run_id="r1",
            from_step_run_id="s1",
            to_step_run_id="s2",
            kind=EdgeKind.DEPENDS_ON,
        )
        assert edge.kind == EdgeKind.DEPENDS_ON


class TestStateVersion:
    def test_create(self):
        actor = ActorRef(provider="test", identifier="agent")
        sv = StateVersion(
            run_id="r1",
            sequence=5,
            state_ref="sha256:abc",
            state_hash="abc",
            actor=actor,
        )
        assert sv.prev_state_version_id is None
        assert sv.sequence == 5


class TestArtifact:
    def test_create(self):
        art = Artifact(
            run_id="r1",
            kind="transcript",
            uri="sha256:abc",
            content_hash="sha256:abc",
            size=1024,
        )
        assert art.content_type == "application/octet-stream"
        assert art.name == ""


class TestApproval:
    def test_create(self):
        actor = ActorRef(provider="test", identifier="agent")
        approval = Approval(
            run_id="r1",
            requested_by=actor,
            authority="github",
            resource="https://github.com/org/repo/pull/1",
        )
        assert approval.status == ApprovalStatus.PENDING
        assert approval.resolved_by is None


class TestLease:
    def test_create(self):
        from datetime import UTC, datetime, timedelta

        actor = ActorRef(provider="test", identifier="agent")
        lease = Lease(
            run_id="r1",
            owner=actor,
            purpose="editing",
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        assert lease.lease_token  # auto-generated
        assert lease.purpose == "editing"


class TestEnums:
    def test_run_status_values(self):
        assert RunStatus.PLANNED == "planned"
        assert RunStatus.RUNNING == "running"

    def test_event_kind_values(self):
        assert EventKind.RUN_CREATED == "run.created"
        assert EventKind.NOTE == "note"
