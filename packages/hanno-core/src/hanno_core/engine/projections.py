"""Projections — derive current state from event replay.

All functions here are pure and side-effect-free.
"""

from __future__ import annotations

from collections.abc import Sequence

from hanno_core.models import Event, EventKind, RunStatus, StepRunStatus


def project_run_status(events: Sequence[Event]) -> RunStatus:
    """Derive the current run status from an event sequence."""
    status = RunStatus.PLANNED
    for event in events:
        match event.kind:
            case EventKind.RUN_STARTED:
                status = RunStatus.RUNNING
            case EventKind.RUN_COMPLETED:
                status = RunStatus.SUCCEEDED
            case EventKind.RUN_FAILED:
                status = RunStatus.FAILED
            case EventKind.RUN_CANCELED:
                status = RunStatus.CANCELED
            case EventKind.RUN_STATUS_CHANGED:
                new_status = event.payload.get("status")
                if new_status and isinstance(new_status, str):
                    status = RunStatus(new_status)
    return status


def project_step_statuses(
    events: Sequence[Event],
) -> dict[str, StepRunStatus]:
    """Derive step statuses from events. Returns {step_run_id: status}."""
    statuses: dict[str, StepRunStatus] = {}
    for event in events:
        if event.step_run_id is None:
            continue
        match event.kind:
            case EventKind.STEP_CREATED:
                statuses[event.step_run_id] = StepRunStatus.QUEUED
            case EventKind.STEP_STARTED:
                statuses[event.step_run_id] = StepRunStatus.RUNNING
            case EventKind.STEP_COMPLETED:
                statuses[event.step_run_id] = StepRunStatus.SUCCEEDED
            case EventKind.STEP_FAILED:
                statuses[event.step_run_id] = StepRunStatus.FAILED
            case EventKind.STEP_SKIPPED:
                statuses[event.step_run_id] = StepRunStatus.SKIPPED
    return statuses


def project_timeline(events: Sequence[Event]) -> list[dict[str, object]]:
    """Build a timeline of key events for AAR/summary purposes."""
    timeline: list[dict[str, object]] = []
    for event in events:
        if event.kind in {
            EventKind.RUN_CREATED,
            EventKind.RUN_STARTED,
            EventKind.RUN_COMPLETED,
            EventKind.RUN_FAILED,
            EventKind.RUN_CANCELED,
            EventKind.STEP_STARTED,
            EventKind.STEP_COMPLETED,
            EventKind.STEP_FAILED,
            EventKind.APPROVAL_REQUESTED,
            EventKind.APPROVAL_GRANTED,
            EventKind.APPROVAL_DENIED,
        }:
            timeline.append({
                "sequence": event.sequence,
                "kind": event.kind.value,
                "timestamp": event.timestamp.isoformat(),
                "actor": f"{event.actor.provider}:{event.actor.identifier}",
                "step_run_id": event.step_run_id,
                "payload": event.payload,
            })
    return timeline
