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
    Session,
    SessionStatus,
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


class TestExternalRef:
    def test_create(self):
        ref = ExternalRef(system="github", ref_type="issue", ref_id="org/repo#42")
        assert ref.system == "github"
        assert ref.ref_type == "issue"
        assert ref.ref_id == "org/repo#42"
        assert ref.url is None

    def test_with_url(self):
        ref = ExternalRef(
            system="github",
            ref_type="issue",
            ref_id="org/repo#42",
            url="https://github.com/org/repo/issues/42",
        )
        assert ref.url == "https://github.com/org/repo/issues/42"

    def test_json_roundtrip(self):
        ref = ExternalRef(
            system="jira", ref_type="ticket", ref_id="PROJ-123", url="https://jira.example.com/PROJ-123"
        )
        data = json.loads(ref.model_dump_json())
        restored = ExternalRef.model_validate(data)
        assert restored == ref


class TestRun:
    def test_defaults(self):
        run = Run(run_type="test")
        assert run.status == RunStatus.PLANNED
        assert run.title == ""
        assert run.external_refs == []
        assert run.labels == {}
        assert run.id  # ULID generated

    def test_with_external_refs(self):
        refs = [
            ExternalRef(system="github", ref_type="issue", ref_id="org/repo#1"),
            ExternalRef(system="zendesk", ref_type="case", ref_id="CASE-99", url="https://zendesk.example.com/99"),
        ]
        run = Run(run_type="support", external_refs=refs)
        assert len(run.external_refs) == 2
        assert run.external_refs[0].system == "github"
        assert run.external_refs[1].url == "https://zendesk.example.com/99"

    def test_json_roundtrip(self):
        run = Run(
            run_type="pr_authoring",
            title="Fix bug",
            labels={"env": "staging"},
            external_refs=[ExternalRef(system="github", ref_type="pr", ref_id="org/repo#5")],
        )
        data = json.loads(run.model_dump_json())
        assert data["run_type"] == "pr_authoring"
        assert data["status"] == "planned"
        assert len(data["external_refs"]) == 1
        restored = Run.model_validate(data)
        assert restored.run_type == "pr_authoring"
        assert restored.external_refs[0].ref_id == "org/repo#5"


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


class TestSession:
    def test_defaults(self):
        session = Session()
        assert session.status == SessionStatus.ACTIVE
        assert session.title == ""
        assert session.external_refs == []
        assert session.labels == {}
        assert session.id  # ULID generated

    def test_with_external_refs(self):
        refs = [
            ExternalRef(system="github", ref_type="pr", ref_id="org/repo#42"),
        ]
        session = Session(title="PR #42 work", external_refs=refs)
        assert len(session.external_refs) == 1
        assert session.external_refs[0].ref_id == "org/repo#42"

    def test_json_roundtrip(self):
        session = Session(
            title="Fix auth bug",
            labels={"team": "backend"},
            external_refs=[
                ExternalRef(system="github", ref_type="pr", ref_id="org/repo#5"),
            ],
        )
        data = json.loads(session.model_dump_json())
        assert data["status"] == "active"
        assert len(data["external_refs"]) == 1
        restored = Session.model_validate(data)
        assert restored.title == "Fix auth bug"
        assert restored.external_refs[0].ref_id == "org/repo#5"

    def test_run_with_session_id(self):
        run = Run(run_type="test", session_id="sess-123")
        assert run.session_id == "sess-123"

    def test_run_session_id_default_none(self):
        run = Run(run_type="test")
        assert run.session_id is None


class TestEnums:
    def test_run_status_values(self):
        assert RunStatus.PLANNED == "planned"
        assert RunStatus.RUNNING == "running"

    def test_event_kind_values(self):
        assert EventKind.RUN_CREATED == "run.created"
        assert EventKind.NOTE == "note"
