"""Status enumerations and kind constants for the workflow ledger."""

from enum import StrEnum


class RunStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    BLOCKED = "blocked"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class StepRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING = "waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class EdgeKind(StrEnum):
    DEPENDS_ON = "depends_on"
    SPAWNED = "spawned"
    LOOP_BACK = "loop_back"
    RELATED = "related"


class EventKind(StrEnum):
    # Run lifecycle
    RUN_CREATED = "run.created"
    RUN_STARTED = "run.started"
    RUN_STATUS_CHANGED = "run.status_changed"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"
    RUN_CANCELED = "run.canceled"

    # Step lifecycle
    STEP_CREATED = "step.created"
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"
    STEP_SKIPPED = "step.skipped"

    # Edges
    EDGE_ADDED = "edge.added"

    # State
    STATE_VERSION_APPENDED = "state.version_appended"

    # Approvals
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_DENIED = "approval.denied"

    # Artifacts
    ARTIFACT_ATTACHED = "artifact.attached"

    # Leases
    LEASE_ACQUIRED = "lease.acquired"
    LEASE_RELEASED = "lease.released"
    LEASE_EXPIRED = "lease.expired"

    # Generic
    NOTE = "note"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    GRANTED = "granted"
    DENIED = "denied"
