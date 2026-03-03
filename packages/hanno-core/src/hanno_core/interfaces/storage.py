"""StorageBackend protocol — the persistence contract for the ledger."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from hanno_core.models import (
    Approval,
    ApprovalStatus,
    Artifact,
    Edge,
    Event,
    EventKind,
    Lease,
    Run,
    RunStatus,
    StateVersion,
    StepRun,
)


class StorageBackend(Protocol):
    """Abstract interface for persistent storage of runs, events, and projections.

    All methods are async. Implementations must be swappable without
    changing skills or the engine layer.
    """

    # Lifecycle

    async def initialize(self) -> None: ...
    async def close(self) -> None: ...

    # Runs

    async def create_run(self, run: Run) -> Run: ...

    async def get_run(self, run_id: str) -> Run | None: ...

    async def list_runs(
        self,
        *,
        status: RunStatus | None = None,
        run_type: str | None = None,
        labels: dict[str, str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Run]: ...

    async def update_run(self, run: Run) -> Run: ...

    # Events (append-only)

    async def append_event(self, event: Event) -> Event: ...

    async def get_event(self, event_id: str) -> Event | None: ...

    async def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        kinds: Sequence[EventKind] | None = None,
        limit: int | None = None,
    ) -> Sequence[Event]: ...

    # Steps

    async def create_step_run(self, step: StepRun) -> StepRun: ...

    async def get_step_run(self, step_run_id: str) -> StepRun | None: ...

    async def list_step_runs(self, run_id: str) -> Sequence[StepRun]: ...

    async def update_step_run(self, step: StepRun) -> StepRun: ...

    # Edges

    async def create_edge(self, edge: Edge) -> Edge: ...

    async def list_edges(self, run_id: str) -> Sequence[Edge]: ...

    # State versions

    async def append_state_version(self, sv: StateVersion) -> StateVersion: ...

    async def get_latest_state_version(self, run_id: str) -> StateVersion | None: ...

    async def list_state_versions(self, run_id: str) -> Sequence[StateVersion]: ...

    # Artifacts

    async def create_artifact(self, artifact: Artifact) -> Artifact: ...

    async def list_artifacts(
        self, run_id: str, *, step_run_id: str | None = None
    ) -> Sequence[Artifact]: ...

    # Approvals

    async def create_approval(self, approval: Approval) -> Approval: ...

    async def get_approval(self, approval_id: str) -> Approval | None: ...

    async def list_approvals(
        self, run_id: str, *, status: ApprovalStatus | None = None
    ) -> Sequence[Approval]: ...

    async def update_approval(self, approval: Approval) -> Approval: ...

    # Leases

    async def create_lease(self, lease: Lease) -> Lease: ...

    async def get_lease(self, lease_id: str) -> Lease | None: ...

    async def list_active_leases(self, run_id: str) -> Sequence[Lease]: ...

    async def delete_lease(self, lease_id: str) -> None: ...

    async def expire_stale_leases(self) -> int: ...

    # Sequence counter

    async def next_sequence(self, run_id: str) -> int: ...
