"""RunLedger — the main API for interacting with the workflow ledger."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hanno_core.hooks.registry import InProcessHookRegistry
from hanno_core.interfaces.artifacts import ArtifactStore
from hanno_core.interfaces.search import SearchBackend
from hanno_core.interfaces.storage import StorageBackend
from hanno_core.models import (
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
from hanno_core.models.identity import ActorRef


class LedgerError(Exception):
    """Base exception for ledger operations."""


class InvalidTransitionError(LedgerError):
    """Raised when a state transition is not allowed."""


_RUN_TERMINAL = {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELED}
_STEP_TERMINAL = {StepRunStatus.SUCCEEDED, StepRunStatus.FAILED, StepRunStatus.SKIPPED}


class RunLedger:
    """The main API for interacting with the workflow ledger.

    Composes a StorageBackend, ArtifactStore, and optional HookRegistry.
    Each mutation validates preconditions, appends event(s), updates projections,
    and fires hooks.
    """

    def __init__(
        self,
        storage: StorageBackend,
        artifacts: ArtifactStore,
        hooks: InProcessHookRegistry | None = None,
        search: SearchBackend | None = None,
    ) -> None:
        self._storage = storage
        self._artifacts = artifacts
        self._hooks = hooks or InProcessHookRegistry()
        self._search = search

    @property
    def search(self) -> SearchBackend | None:
        """Optional search backend for querying indexed ledger content."""
        return self._search

    # --- Session lifecycle ---

    async def create_session(
        self,
        *,
        title: str = "",
        external_refs: list[ExternalRef] | None = None,
        labels: dict[str, str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> Session:
        session = Session(
            title=title,
            external_refs=external_refs or [],
            labels=labels or {},
            metadata=metadata or {},
        )
        return await self._storage.create_session(session)

    async def get_session(self, session_id: str) -> Session | None:
        return await self._storage.get_session(session_id)

    async def close_session(self, session_id: str) -> Session:
        session = await self._require_session(session_id)
        if session.status != SessionStatus.ACTIVE:
            msg = f"Cannot close session in status {session.status}"
            raise InvalidTransitionError(msg)
        session.status = SessionStatus.CLOSED
        session.updated_at = datetime.now(UTC)
        return await self._storage.update_session(session)

    async def archive_session(self, session_id: str) -> Session:
        session = await self._require_session(session_id)
        if session.status == SessionStatus.ARCHIVED:
            msg = "Session is already archived"
            raise InvalidTransitionError(msg)
        session.status = SessionStatus.ARCHIVED
        session.updated_at = datetime.now(UTC)
        return await self._storage.update_session(session)

    async def list_sessions(self, **kwargs: object) -> list[Session]:
        return list(await self._storage.list_sessions(**kwargs))  # type: ignore[arg-type]

    async def find_sessions_by_external_ref(
        self,
        *,
        system: str,
        ref_type: str,
        ref_id: str,
        status: SessionStatus | None = None,
    ) -> list[Session]:
        return list(
            await self._storage.find_sessions_by_external_ref(
                system=system, ref_type=ref_type, ref_id=ref_id, status=status,
            )
        )

    async def list_session_runs(
        self, session_id: str, **kwargs: object
    ) -> list[Run]:
        return list(
            await self._storage.list_runs(session_id=session_id, **kwargs)  # type: ignore[arg-type]
        )

    # --- Run lifecycle ---

    async def create_run(
        self,
        run_type: str,
        *,
        actor: ActorRef,
        title: str = "",
        external_refs: list[ExternalRef] | None = None,
        labels: dict[str, str] | None = None,
        metadata: dict[str, object] | None = None,
        session_id: str | None = None,
    ) -> Run:
        run = Run(
            run_type=run_type,
            title=title,
            external_refs=external_refs or [],
            labels=labels or {},
            metadata=metadata or {},
            session_id=session_id,
        )
        run = await self._storage.create_run(run)
        await self._append_event(
            run.id, EventKind.RUN_CREATED, actor, payload={"run_type": run_type}
        )
        return run

    async def start_run(self, run_id: str, *, actor: ActorRef) -> Run:
        run = await self._require_run(run_id)
        self._check_run_transition(run, RunStatus.RUNNING)
        run.status = RunStatus.RUNNING
        run.updated_at = datetime.now(UTC)
        run = await self._storage.update_run(run)
        await self._append_event(run_id, EventKind.RUN_STARTED, actor)
        return run

    async def complete_run(self, run_id: str, *, actor: ActorRef) -> Run:
        run = await self._require_run(run_id)
        self._check_run_transition(run, RunStatus.SUCCEEDED)
        run.status = RunStatus.SUCCEEDED
        run.updated_at = datetime.now(UTC)
        run = await self._storage.update_run(run)
        await self._append_event(run_id, EventKind.RUN_COMPLETED, actor)
        await self._hooks.fire_run_completed(run_id, RunStatus.SUCCEEDED)
        return run

    async def fail_run(
        self, run_id: str, *, actor: ActorRef, error: str = ""
    ) -> Run:
        run = await self._require_run(run_id)
        self._check_run_transition(run, RunStatus.FAILED)
        run.status = RunStatus.FAILED
        run.updated_at = datetime.now(UTC)
        run = await self._storage.update_run(run)
        await self._append_event(
            run_id, EventKind.RUN_FAILED, actor, payload={"error": error}
        )
        await self._hooks.fire_run_completed(run_id, RunStatus.FAILED)
        return run

    async def cancel_run(
        self, run_id: str, *, actor: ActorRef, reason: str = ""
    ) -> Run:
        run = await self._require_run(run_id)
        self._check_run_transition(run, RunStatus.CANCELED)
        run.status = RunStatus.CANCELED
        run.updated_at = datetime.now(UTC)
        run = await self._storage.update_run(run)
        await self._append_event(
            run_id, EventKind.RUN_CANCELED, actor, payload={"reason": reason}
        )
        await self._hooks.fire_run_completed(run_id, RunStatus.CANCELED)
        return run

    async def set_run_waiting(self, run_id: str, *, actor: ActorRef) -> Run:
        run = await self._require_run(run_id)
        self._check_run_transition(run, RunStatus.WAITING_HUMAN)
        run.status = RunStatus.WAITING_HUMAN
        run.updated_at = datetime.now(UTC)
        run = await self._storage.update_run(run)
        await self._append_event(
            run_id,
            EventKind.RUN_STATUS_CHANGED,
            actor,
            payload={"status": RunStatus.WAITING_HUMAN},
        )
        return run

    async def set_run_blocked(self, run_id: str, *, actor: ActorRef) -> Run:
        run = await self._require_run(run_id)
        self._check_run_transition(run, RunStatus.BLOCKED)
        run.status = RunStatus.BLOCKED
        run.updated_at = datetime.now(UTC)
        run = await self._storage.update_run(run)
        await self._append_event(
            run_id,
            EventKind.RUN_STATUS_CHANGED,
            actor,
            payload={"status": RunStatus.BLOCKED},
        )
        return run

    async def resume_run(self, run_id: str, *, actor: ActorRef) -> Run:
        """Resume a waiting/blocked run back to running."""
        run = await self._require_run(run_id)
        if run.status not in {RunStatus.WAITING_HUMAN, RunStatus.BLOCKED}:
            msg = f"Cannot resume run in status {run.status}"
            raise InvalidTransitionError(msg)
        run.status = RunStatus.RUNNING
        run.updated_at = datetime.now(UTC)
        run = await self._storage.update_run(run)
        await self._append_event(
            run_id,
            EventKind.RUN_STATUS_CHANGED,
            actor,
            payload={"status": RunStatus.RUNNING},
        )
        return run

    async def get_run(self, run_id: str) -> Run | None:
        return await self._storage.get_run(run_id)

    async def list_runs(self, **kwargs: object) -> list[Run]:
        return list(await self._storage.list_runs(**kwargs))  # type: ignore[arg-type]

    async def find_runs_by_external_ref(
        self,
        *,
        system: str,
        ref_type: str,
        ref_id: str,
        status: RunStatus | None = None,
    ) -> list[Run]:
        return list(
            await self._storage.find_runs_by_external_ref(
                system=system, ref_type=ref_type, ref_id=ref_id, status=status,
            )
        )

    # --- Step lifecycle ---

    async def add_step(
        self,
        run_id: str,
        *,
        step_name: str,
        actor: ActorRef,
        iteration: int = 0,
        parent_step_run_id: str | None = None,
        depends_on: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> StepRun:
        await self._require_run(run_id)
        step = StepRun(
            run_id=run_id,
            step_name=step_name,
            iteration=iteration,
            parent_step_run_id=parent_step_run_id,
            metadata=metadata or {},
        )
        step = await self._storage.create_step_run(step)
        await self._append_event(
            run_id,
            EventKind.STEP_CREATED,
            actor,
            step_run_id=step.id,
            payload={"step_name": step_name, "iteration": iteration},
        )

        for dep_id in depends_on or []:
            edge = Edge(
                run_id=run_id,
                from_step_run_id=dep_id,
                to_step_run_id=step.id,
                kind=EdgeKind.DEPENDS_ON,
            )
            await self._storage.create_edge(edge)
            await self._append_event(
                run_id,
                EventKind.EDGE_ADDED,
                actor,
                payload={
                    "from": dep_id,
                    "to": step.id,
                    "kind": EdgeKind.DEPENDS_ON,
                },
            )

        return step

    async def start_step(self, step_run_id: str, *, actor: ActorRef) -> StepRun:
        step = await self._require_step(step_run_id)
        if step.status != StepRunStatus.QUEUED:
            msg = f"Cannot start step in status {step.status}"
            raise InvalidTransitionError(msg)
        step.status = StepRunStatus.RUNNING
        step.started_at = datetime.now(UTC)
        step = await self._storage.update_step_run(step)
        await self._append_event(
            step.run_id,
            EventKind.STEP_STARTED,
            actor,
            step_run_id=step.id,
        )
        return step

    async def complete_step(
        self,
        step_run_id: str,
        *,
        actor: ActorRef,
        summary: str = "",
        output: dict[str, object] | None = None,
    ) -> StepRun:
        step = await self._require_step(step_run_id)
        if step.status != StepRunStatus.RUNNING:
            msg = f"Cannot complete step in status {step.status}"
            raise InvalidTransitionError(msg)
        step.status = StepRunStatus.SUCCEEDED
        step.ended_at = datetime.now(UTC)
        step.summary = summary
        step = await self._storage.update_step_run(step)
        await self._append_event(
            step.run_id,
            EventKind.STEP_COMPLETED,
            actor,
            step_run_id=step.id,
            payload={"output": output or {}},
        )
        return step

    async def fail_step(
        self,
        step_run_id: str,
        *,
        actor: ActorRef,
        error: str = "",
    ) -> StepRun:
        step = await self._require_step(step_run_id)
        if step.status != StepRunStatus.RUNNING:
            msg = f"Cannot fail step in status {step.status}"
            raise InvalidTransitionError(msg)
        step.status = StepRunStatus.FAILED
        step.ended_at = datetime.now(UTC)
        step.summary = error
        step = await self._storage.update_step_run(step)
        await self._append_event(
            step.run_id,
            EventKind.STEP_FAILED,
            actor,
            step_run_id=step.id,
            payload={"error": error},
        )
        return step

    async def skip_step(self, step_run_id: str, *, actor: ActorRef) -> StepRun:
        step = await self._require_step(step_run_id)
        if step.status not in {StepRunStatus.QUEUED, StepRunStatus.WAITING}:
            msg = f"Cannot skip step in status {step.status}"
            raise InvalidTransitionError(msg)
        step.status = StepRunStatus.SKIPPED
        step.ended_at = datetime.now(UTC)
        step = await self._storage.update_step_run(step)
        await self._append_event(
            step.run_id,
            EventKind.STEP_SKIPPED,
            actor,
            step_run_id=step.id,
        )
        return step

    async def get_step(self, step_run_id: str) -> StepRun | None:
        return await self._storage.get_step_run(step_run_id)

    async def list_steps(self, run_id: str) -> list[StepRun]:
        return list(await self._storage.list_step_runs(run_id))

    # --- Edges ---

    async def add_edge(
        self,
        run_id: str,
        *,
        from_step_run_id: str,
        to_step_run_id: str,
        kind: EdgeKind,
        actor: ActorRef,
        metadata: dict[str, object] | None = None,
    ) -> Edge:
        edge = Edge(
            run_id=run_id,
            from_step_run_id=from_step_run_id,
            to_step_run_id=to_step_run_id,
            kind=kind,
            metadata=metadata or {},
        )
        edge = await self._storage.create_edge(edge)
        await self._append_event(
            run_id,
            EventKind.EDGE_ADDED,
            actor,
            payload={
                "from": from_step_run_id,
                "to": to_step_run_id,
                "kind": kind,
            },
        )
        return edge

    async def list_edges(self, run_id: str) -> list[Edge]:
        return list(await self._storage.list_edges(run_id))

    # --- Artifacts ---

    async def attach_artifact(
        self,
        run_id: str,
        *,
        data: bytes,
        kind: str,
        actor: ActorRef,
        name: str = "",
        content_type: str = "application/octet-stream",
        step_run_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> Artifact:
        await self._require_run(run_id)
        ref = await self._artifacts.store(data, content_type=content_type)
        artifact = Artifact(
            run_id=run_id,
            step_run_id=step_run_id,
            kind=kind,
            uri=ref,
            content_hash=ref,
            size=len(data),
            content_type=content_type,
            name=name,
            metadata=metadata or {},
        )
        artifact = await self._storage.create_artifact(artifact)
        await self._append_event(
            run_id,
            EventKind.ARTIFACT_ATTACHED,
            actor,
            step_run_id=step_run_id,
            payload={"artifact_id": artifact.id, "kind": kind, "name": name},
        )
        return artifact

    async def retrieve_artifact(self, artifact_id: str) -> bytes:
        """Retrieve artifact content by ID."""
        artifact = await self._storage.get_artifact(artifact_id)
        if artifact is None:
            msg = f"Artifact not found: {artifact_id}"
            raise LedgerError(msg)
        return await self._artifacts.retrieve(artifact.uri)

    async def list_artifacts(
        self,
        run_id: str,
        *,
        step_run_id: str | None = None,
        kind: str | None = None,
    ) -> list[Artifact]:
        return list(
            await self._storage.list_artifacts(
                run_id, step_run_id=step_run_id, kind=kind,
            )
        )

    # --- Approvals ---

    async def request_approval(
        self,
        run_id: str,
        *,
        actor: ActorRef,
        authority: str = "",
        resource: str = "",
        criteria: dict[str, object] | None = None,
        step_run_id: str | None = None,
    ) -> Approval:
        await self._require_run(run_id)
        approval = Approval(
            run_id=run_id,
            step_run_id=step_run_id,
            authority=authority,
            resource=resource,
            criteria=criteria or {},
            requested_by=actor,
        )
        approval = await self._storage.create_approval(approval)
        await self._append_event(
            run_id,
            EventKind.APPROVAL_REQUESTED,
            actor,
            step_run_id=step_run_id,
            payload={"approval_id": approval.id, "authority": authority},
        )
        return approval

    async def grant_approval(
        self, approval_id: str, *, actor: ActorRef
    ) -> Approval:
        approval = await self._require_approval(approval_id)
        if approval.status != ApprovalStatus.PENDING:
            msg = f"Approval is already {approval.status}"
            raise InvalidTransitionError(msg)
        approval.status = ApprovalStatus.GRANTED
        approval.resolved_by = actor
        approval.resolved_at = datetime.now(UTC)
        approval = await self._storage.update_approval(approval)
        await self._append_event(
            approval.run_id,
            EventKind.APPROVAL_GRANTED,
            actor,
            step_run_id=approval.step_run_id,
            payload={"approval_id": approval_id},
        )
        return approval

    async def deny_approval(
        self, approval_id: str, *, actor: ActorRef, reason: str = ""
    ) -> Approval:
        approval = await self._require_approval(approval_id)
        if approval.status != ApprovalStatus.PENDING:
            msg = f"Approval is already {approval.status}"
            raise InvalidTransitionError(msg)
        approval.status = ApprovalStatus.DENIED
        approval.resolved_by = actor
        approval.resolved_at = datetime.now(UTC)
        approval.reason = reason
        approval = await self._storage.update_approval(approval)
        await self._append_event(
            approval.run_id,
            EventKind.APPROVAL_DENIED,
            actor,
            step_run_id=approval.step_run_id,
            payload={"approval_id": approval_id, "reason": reason},
        )
        return approval

    async def list_approvals(
        self, run_id: str, *, status: ApprovalStatus | None = None
    ) -> list[Approval]:
        return list(await self._storage.list_approvals(run_id, status=status))

    # --- Leases ---

    async def acquire_lease(
        self,
        run_id: str,
        *,
        actor: ActorRef,
        purpose: str = "",
        ttl_seconds: int = 300,
    ) -> Lease:
        await self._require_run(run_id)
        lease = Lease(
            run_id=run_id,
            owner=actor,
            purpose=purpose,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        )
        lease = await self._storage.create_lease(lease)
        await self._append_event(
            run_id,
            EventKind.LEASE_ACQUIRED,
            actor,
            payload={"lease_id": lease.id, "purpose": purpose, "ttl": ttl_seconds},
        )
        return lease

    async def release_lease(
        self, lease_id: str, *, actor: ActorRef
    ) -> None:
        lease = await self._storage.get_lease(lease_id)
        if lease is None:
            msg = f"Lease not found: {lease_id}"
            raise LedgerError(msg)
        await self._storage.delete_lease(lease_id)
        await self._append_event(
            lease.run_id,
            EventKind.LEASE_RELEASED,
            actor,
            payload={"lease_id": lease_id},
        )

    async def list_active_leases(self, run_id: str) -> list[Lease]:
        return list(await self._storage.list_active_leases(run_id))

    # --- Events ---

    async def list_events(self, run_id: str, **kwargs: object) -> list[Event]:
        return list(await self._storage.list_events(run_id, **kwargs))  # type: ignore[arg-type]

    async def add_note(
        self,
        run_id: str,
        *,
        actor: ActorRef,
        message: str,
        step_run_id: str | None = None,
    ) -> Event:
        return await self._append_event(
            run_id,
            EventKind.NOTE,
            actor,
            step_run_id=step_run_id,
            payload={"message": message},
        )

    # --- State versions ---

    async def append_state_version(
        self,
        run_id: str,
        *,
        state_data: bytes,
        actor: ActorRef,
    ) -> StateVersion:
        ref = await self._artifacts.store(state_data, content_type="application/json")
        import hashlib

        state_hash = hashlib.sha256(state_data).hexdigest()

        latest = await self._storage.get_latest_state_version(run_id)
        seq = await self._storage.next_sequence(run_id)

        sv = StateVersion(
            run_id=run_id,
            sequence=seq,
            prev_state_version_id=latest.id if latest else None,
            state_ref=ref,
            state_hash=state_hash,
            actor=actor,
        )
        # Decrement seq since next_sequence auto-incremented for the event we'll append
        # Actually, the state version's sequence corresponds to the event stream position
        sv = await self._storage.append_state_version(sv)
        await self._append_event(
            run_id,
            EventKind.STATE_VERSION_APPENDED,
            actor,
            payload={"state_version_id": sv.id, "state_ref": ref},
        )
        return sv

    async def get_latest_state(self, run_id: str) -> StateVersion | None:
        return await self._storage.get_latest_state_version(run_id)

    # --- Internal helpers ---

    async def _append_event(
        self,
        run_id: str,
        kind: EventKind,
        actor: ActorRef,
        *,
        step_run_id: str | None = None,
        payload: dict[str, object] | None = None,
        parent_event_id: str | None = None,
    ) -> Event:
        seq = await self._storage.next_sequence(run_id)
        event = Event(
            run_id=run_id,
            sequence=seq,
            kind=kind,
            actor=actor,
            payload=payload or {},
            step_run_id=step_run_id,
            parent_event_id=parent_event_id,
        )
        event = await self._storage.append_event(event)
        await self._hooks.fire_event_appended(event)
        return event

    async def _require_run(self, run_id: str) -> Run:
        run = await self._storage.get_run(run_id)
        if run is None:
            msg = f"Run not found: {run_id}"
            raise LedgerError(msg)
        return run

    async def _require_step(self, step_run_id: str) -> StepRun:
        step = await self._storage.get_step_run(step_run_id)
        if step is None:
            msg = f"Step not found: {step_run_id}"
            raise LedgerError(msg)
        return step

    async def _require_approval(self, approval_id: str) -> Approval:
        approval = await self._storage.get_approval(approval_id)
        if approval is None:
            msg = f"Approval not found: {approval_id}"
            raise LedgerError(msg)
        return approval

    async def _require_session(self, session_id: str) -> Session:
        session = await self._storage.get_session(session_id)
        if session is None:
            msg = f"Session not found: {session_id}"
            raise LedgerError(msg)
        return session

    @staticmethod
    def _check_run_transition(run: Run, target: RunStatus) -> None:
        """Validate run status transitions."""
        allowed: dict[RunStatus, set[RunStatus]] = {
            RunStatus.PLANNED: {RunStatus.RUNNING, RunStatus.CANCELED},
            RunStatus.RUNNING: {
                RunStatus.WAITING_HUMAN,
                RunStatus.BLOCKED,
                RunStatus.SUCCEEDED,
                RunStatus.FAILED,
                RunStatus.CANCELED,
            },
            RunStatus.WAITING_HUMAN: {
                RunStatus.RUNNING,
                RunStatus.CANCELED,
                RunStatus.FAILED,
            },
            RunStatus.BLOCKED: {
                RunStatus.RUNNING,
                RunStatus.CANCELED,
                RunStatus.FAILED,
            },
        }
        if run.status in _RUN_TERMINAL:
            msg = f"Run is in terminal status {run.status}"
            raise InvalidTransitionError(msg)
        if target not in allowed.get(run.status, set()):
            msg = f"Cannot transition from {run.status} to {target}"
            raise InvalidTransitionError(msg)
