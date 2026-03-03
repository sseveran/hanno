"""Tests for event projections."""

from hanno_core.engine.projections import (
    project_run_status,
    project_step_statuses,
    project_timeline,
)
from hanno_core.models import Event, EventKind, RunStatus, StepRunStatus
from hanno_core.models.identity import ActorRef


def _actor():
    return ActorRef(provider="test", identifier="agent")


def _event(seq: int, kind: EventKind, step_run_id: str | None = None, **payload):
    return Event(
        run_id="r1",
        sequence=seq,
        kind=kind,
        actor=_actor(),
        step_run_id=step_run_id,
        payload=payload,
    )


class TestProjectRunStatus:
    def test_empty_events(self):
        assert project_run_status([]) == RunStatus.PLANNED

    def test_created_only(self):
        events = [_event(1, EventKind.RUN_CREATED)]
        assert project_run_status(events) == RunStatus.PLANNED

    def test_started(self):
        events = [
            _event(1, EventKind.RUN_CREATED),
            _event(2, EventKind.RUN_STARTED),
        ]
        assert project_run_status(events) == RunStatus.RUNNING

    def test_completed(self):
        events = [
            _event(1, EventKind.RUN_CREATED),
            _event(2, EventKind.RUN_STARTED),
            _event(3, EventKind.RUN_COMPLETED),
        ]
        assert project_run_status(events) == RunStatus.SUCCEEDED

    def test_failed(self):
        events = [
            _event(1, EventKind.RUN_CREATED),
            _event(2, EventKind.RUN_STARTED),
            _event(3, EventKind.RUN_FAILED),
        ]
        assert project_run_status(events) == RunStatus.FAILED

    def test_canceled(self):
        events = [
            _event(1, EventKind.RUN_CREATED),
            _event(2, EventKind.RUN_CANCELED),
        ]
        assert project_run_status(events) == RunStatus.CANCELED

    def test_waiting_then_resume(self):
        events = [
            _event(1, EventKind.RUN_CREATED),
            _event(2, EventKind.RUN_STARTED),
            _event(3, EventKind.RUN_STATUS_CHANGED, status="waiting_human"),
            _event(4, EventKind.RUN_STATUS_CHANGED, status="running"),
        ]
        assert project_run_status(events) == RunStatus.RUNNING

    def test_idempotent(self):
        events = [
            _event(1, EventKind.RUN_CREATED),
            _event(2, EventKind.RUN_STARTED),
        ]
        s1 = project_run_status(events)
        s2 = project_run_status(events)
        assert s1 == s2


class TestProjectStepStatuses:
    def test_empty(self):
        assert project_step_statuses([]) == {}

    def test_step_lifecycle(self):
        events = [
            _event(1, EventKind.STEP_CREATED, step_run_id="s1"),
            _event(2, EventKind.STEP_STARTED, step_run_id="s1"),
            _event(3, EventKind.STEP_COMPLETED, step_run_id="s1"),
        ]
        statuses = project_step_statuses(events)
        assert statuses["s1"] == StepRunStatus.SUCCEEDED

    def test_multiple_steps(self):
        events = [
            _event(1, EventKind.STEP_CREATED, step_run_id="s1"),
            _event(2, EventKind.STEP_CREATED, step_run_id="s2"),
            _event(3, EventKind.STEP_STARTED, step_run_id="s1"),
            _event(4, EventKind.STEP_COMPLETED, step_run_id="s1"),
            _event(5, EventKind.STEP_STARTED, step_run_id="s2"),
            _event(6, EventKind.STEP_FAILED, step_run_id="s2"),
        ]
        statuses = project_step_statuses(events)
        assert statuses["s1"] == StepRunStatus.SUCCEEDED
        assert statuses["s2"] == StepRunStatus.FAILED


class TestProjectTimeline:
    def test_filters_key_events(self):
        events = [
            _event(1, EventKind.RUN_CREATED),
            _event(2, EventKind.RUN_STARTED),
            _event(3, EventKind.NOTE),  # should be excluded
            _event(4, EventKind.STEP_STARTED, step_run_id="s1"),
            _event(5, EventKind.RUN_COMPLETED),
        ]
        timeline = project_timeline(events)
        assert len(timeline) == 4  # NOTE excluded
        kinds = [t["kind"] for t in timeline]
        assert "note" not in kinds
