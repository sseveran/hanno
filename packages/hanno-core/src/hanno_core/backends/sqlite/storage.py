"""SQLite storage backend implementation."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import aiosqlite

from hanno_core.models import (
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
from hanno_core.models.identity import ActorRef

from . import queries as Q
from .migrations import run_migrations


class SqliteStorageBackend:
    """SQLite implementation of the StorageBackend protocol.

    Uses WAL mode for better concurrency and foreign keys for integrity.
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        self._db_path = str(db_path)
        self._conn: aiosqlite.Connection | None = None

    @property
    def _db(self) -> aiosqlite.Connection:
        if self._conn is None:
            msg = "Storage not initialized. Call initialize() first."
            raise RuntimeError(msg)
        return self._conn

    async def initialize(self) -> None:
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await run_migrations(self._conn)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    # --- Runs ---

    async def create_run(self, run: Run) -> Run:
        await self._db.execute(
            Q.INSERT_RUN,
            (
                run.id,
                run.run_type,
                run.status.value,
                run.title,
                json.dumps(run.links),
                json.dumps(run.labels),
                json.dumps(run.metadata, default=str),
                run.created_at.isoformat(),
                run.updated_at.isoformat(),
            ),
        )
        await self._db.commit()
        return run

    async def get_run(self, run_id: str) -> Run | None:
        cursor = await self._db.execute(Q.SELECT_RUN, (run_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_run(row)

    async def list_runs(
        self,
        *,
        status: RunStatus | None = None,
        run_type: str | None = None,
        labels: dict[str, str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Run]:
        clauses: list[str] = []
        params: list[object] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value)
        if run_type is not None:
            clauses.append("run_type = ?")
            params.append(run_type)

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM runs{where} ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        runs = [_row_to_run(r) for r in rows]

        if labels:
            runs = [
                r
                for r in runs
                if all(r.labels.get(k) == v for k, v in labels.items())
            ]
        return runs

    async def update_run(self, run: Run) -> Run:
        await self._db.execute(
            Q.UPDATE_RUN,
            (
                run.status.value,
                run.title,
                json.dumps(run.links),
                json.dumps(run.labels),
                json.dumps(run.metadata, default=str),
                run.updated_at.isoformat(),
                run.id,
            ),
        )
        await self._db.commit()
        return run

    # --- Events ---

    async def append_event(self, event: Event) -> Event:
        await self._db.execute(
            Q.INSERT_EVENT,
            (
                event.id,
                event.run_id,
                event.sequence,
                event.kind.value,
                event.actor.model_dump_json(),
                json.dumps(event.payload, default=str),
                event.step_run_id,
                event.parent_event_id,
                event.trace_id,
                event.span_id,
                event.timestamp.isoformat(),
            ),
        )
        await self._db.commit()
        return event

    async def get_event(self, event_id: str) -> Event | None:
        cursor = await self._db.execute(Q.SELECT_EVENT, (event_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_event(row)

    async def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        kinds: Sequence[EventKind] | None = None,
        limit: int | None = None,
    ) -> Sequence[Event]:
        clauses = ["run_id = ?", "sequence > ?"]
        params: list[object] = [run_id, after_sequence]

        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            clauses.append(f"kind IN ({placeholders})")
            params.extend(k.value for k in kinds)

        where = " AND ".join(clauses)
        sql = f"SELECT * FROM events WHERE {where} ORDER BY sequence ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()
        return [_row_to_event(r) for r in rows]

    # --- Steps ---

    async def create_step_run(self, step: StepRun) -> StepRun:
        await self._db.execute(
            Q.INSERT_STEP_RUN,
            (
                step.id,
                step.run_id,
                step.step_name,
                step.status.value,
                step.iteration,
                step.parent_step_run_id,
                step.started_at.isoformat() if step.started_at else None,
                step.ended_at.isoformat() if step.ended_at else None,
                step.summary,
                json.dumps(step.metadata, default=str),
                step.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return step

    async def get_step_run(self, step_run_id: str) -> StepRun | None:
        cursor = await self._db.execute(Q.SELECT_STEP_RUN, (step_run_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_step_run(row)

    async def list_step_runs(self, run_id: str) -> Sequence[StepRun]:
        cursor = await self._db.execute(
            "SELECT * FROM step_runs WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        )
        rows = await cursor.fetchall()
        return [_row_to_step_run(r) for r in rows]

    async def update_step_run(self, step: StepRun) -> StepRun:
        await self._db.execute(
            Q.UPDATE_STEP_RUN,
            (
                step.status.value,
                step.started_at.isoformat() if step.started_at else None,
                step.ended_at.isoformat() if step.ended_at else None,
                step.summary,
                json.dumps(step.metadata, default=str),
                step.id,
            ),
        )
        await self._db.commit()
        return step

    # --- Edges ---

    async def create_edge(self, edge: Edge) -> Edge:
        await self._db.execute(
            Q.INSERT_EDGE,
            (
                edge.id,
                edge.run_id,
                edge.from_step_run_id,
                edge.to_step_run_id,
                edge.kind.value,
                json.dumps(edge.metadata, default=str),
            ),
        )
        await self._db.commit()
        return edge

    async def list_edges(self, run_id: str) -> Sequence[Edge]:
        cursor = await self._db.execute(
            "SELECT * FROM edges WHERE run_id = ?", (run_id,)
        )
        rows = await cursor.fetchall()
        return [_row_to_edge(r) for r in rows]

    # --- State Versions ---

    async def append_state_version(self, sv: StateVersion) -> StateVersion:
        await self._db.execute(
            Q.INSERT_STATE_VERSION,
            (
                sv.id,
                sv.run_id,
                sv.sequence,
                sv.prev_state_version_id,
                sv.state_ref,
                sv.state_hash,
                sv.actor.model_dump_json(),
                sv.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return sv

    async def get_latest_state_version(self, run_id: str) -> StateVersion | None:
        cursor = await self._db.execute(
            "SELECT * FROM state_versions WHERE run_id = ? ORDER BY sequence DESC LIMIT 1",
            (run_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_state_version(row)

    async def list_state_versions(self, run_id: str) -> Sequence[StateVersion]:
        cursor = await self._db.execute(
            "SELECT * FROM state_versions WHERE run_id = ? ORDER BY sequence ASC",
            (run_id,),
        )
        rows = await cursor.fetchall()
        return [_row_to_state_version(r) for r in rows]

    # --- Artifacts ---

    async def create_artifact(self, artifact: Artifact) -> Artifact:
        await self._db.execute(
            Q.INSERT_ARTIFACT,
            (
                artifact.id,
                artifact.run_id,
                artifact.step_run_id,
                artifact.kind,
                artifact.uri,
                artifact.content_hash,
                artifact.size,
                artifact.content_type,
                artifact.name,
                json.dumps(artifact.metadata, default=str),
                artifact.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return artifact

    async def list_artifacts(
        self, run_id: str, *, step_run_id: str | None = None
    ) -> Sequence[Artifact]:
        if step_run_id:
            cursor = await self._db.execute(
                "SELECT * FROM artifacts WHERE run_id = ? AND step_run_id = ?"
                " ORDER BY created_at ASC",
                (run_id, step_run_id),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM artifacts WHERE run_id = ? ORDER BY created_at ASC",
                (run_id,),
            )
        rows = await cursor.fetchall()
        return [_row_to_artifact(r) for r in rows]

    # --- Approvals ---

    async def create_approval(self, approval: Approval) -> Approval:
        await self._db.execute(
            Q.INSERT_APPROVAL,
            (
                approval.id,
                approval.run_id,
                approval.step_run_id,
                approval.status.value,
                approval.authority,
                approval.resource,
                json.dumps(approval.criteria, default=str),
                approval.requested_by.model_dump_json(),
                approval.resolved_by.model_dump_json() if approval.resolved_by else None,
                approval.reason,
                approval.requested_at.isoformat(),
                approval.resolved_at.isoformat() if approval.resolved_at else None,
            ),
        )
        await self._db.commit()
        return approval

    async def get_approval(self, approval_id: str) -> Approval | None:
        cursor = await self._db.execute(Q.SELECT_APPROVAL, (approval_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_approval(row)

    async def list_approvals(
        self, run_id: str, *, status: ApprovalStatus | None = None
    ) -> Sequence[Approval]:
        if status:
            cursor = await self._db.execute(
                "SELECT * FROM approvals WHERE run_id = ? AND status = ?"
                " ORDER BY requested_at ASC",
                (run_id, status.value),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM approvals WHERE run_id = ? ORDER BY requested_at ASC",
                (run_id,),
            )
        rows = await cursor.fetchall()
        return [_row_to_approval(r) for r in rows]

    async def update_approval(self, approval: Approval) -> Approval:
        await self._db.execute(
            Q.UPDATE_APPROVAL,
            (
                approval.status.value,
                approval.resolved_by.model_dump_json() if approval.resolved_by else None,
                approval.reason,
                approval.resolved_at.isoformat() if approval.resolved_at else None,
                approval.id,
            ),
        )
        await self._db.commit()
        return approval

    # --- Leases ---

    async def create_lease(self, lease: Lease) -> Lease:
        await self._db.execute(
            Q.INSERT_LEASE,
            (
                lease.id,
                lease.run_id,
                lease.lease_token,
                lease.owner.model_dump_json(),
                lease.purpose,
                lease.acquired_at.isoformat(),
                lease.expires_at.isoformat(),
            ),
        )
        await self._db.commit()
        return lease

    async def get_lease(self, lease_id: str) -> Lease | None:
        cursor = await self._db.execute(Q.SELECT_LEASE, (lease_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_lease(row)

    async def list_active_leases(self, run_id: str) -> Sequence[Lease]:
        cursor = await self._db.execute(
            "SELECT * FROM leases WHERE run_id = ? AND expires_at > datetime('now')",
            (run_id,),
        )
        rows = await cursor.fetchall()
        return [_row_to_lease(r) for r in rows]

    async def delete_lease(self, lease_id: str) -> None:
        await self._db.execute(Q.DELETE_LEASE, (lease_id,))
        await self._db.commit()

    async def expire_stale_leases(self) -> int:
        cursor = await self._db.execute(Q.DELETE_EXPIRED_LEASES)
        await self._db.commit()
        return cursor.rowcount

    # --- Sequence Counter ---

    async def next_sequence(self, run_id: str) -> int:
        await self._db.execute(Q.UPSERT_SEQUENCE, (run_id,))
        cursor = await self._db.execute(Q.SELECT_SEQUENCE, (run_id,))
        row = await cursor.fetchone()
        await self._db.commit()
        return row[0]  # type: ignore[index]


# --- Row conversion helpers ---

from datetime import UTC, datetime  # noqa: E402


def _parse_dt(s: str | None) -> datetime | None:
    if s is None:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _parse_dt_required(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _row_to_run(row: aiosqlite.Row) -> Run:
    return Run(
        id=row["id"],
        run_type=row["run_type"],
        status=RunStatus(row["status"]),
        title=row["title"],
        links=json.loads(row["links_json"]),
        labels=json.loads(row["labels_json"]),
        metadata=json.loads(row["metadata_json"]),
        created_at=_parse_dt_required(row["created_at"]),
        updated_at=_parse_dt_required(row["updated_at"]),
    )


def _row_to_event(row: aiosqlite.Row) -> Event:
    return Event(
        id=row["id"],
        run_id=row["run_id"],
        sequence=row["sequence"],
        kind=EventKind(row["kind"]),
        actor=ActorRef.model_validate_json(row["actor_json"]),
        payload=json.loads(row["payload_json"]),
        step_run_id=row["step_run_id"],
        parent_event_id=row["parent_event_id"],
        trace_id=row["trace_id"],
        span_id=row["span_id"],
        timestamp=_parse_dt_required(row["timestamp"]),
    )


def _row_to_step_run(row: aiosqlite.Row) -> StepRun:
    return StepRun(
        id=row["id"],
        run_id=row["run_id"],
        step_name=row["step_name"],
        status=StepRunStatus(row["status"]),
        iteration=row["iteration"],
        parent_step_run_id=row["parent_step_run_id"],
        started_at=_parse_dt(row["started_at"]),
        ended_at=_parse_dt(row["ended_at"]),
        summary=row["summary"],
        metadata=json.loads(row["metadata_json"]),
        created_at=_parse_dt_required(row["created_at"]),
    )


def _row_to_edge(row: aiosqlite.Row) -> Edge:
    return Edge(
        id=row["id"],
        run_id=row["run_id"],
        from_step_run_id=row["from_step_run_id"],
        to_step_run_id=row["to_step_run_id"],
        kind=EdgeKind(row["kind"]),
        metadata=json.loads(row["metadata_json"]),
    )


def _row_to_state_version(row: aiosqlite.Row) -> StateVersion:
    return StateVersion(
        id=row["id"],
        run_id=row["run_id"],
        sequence=row["sequence"],
        prev_state_version_id=row["prev_state_version_id"],
        state_ref=row["state_ref"],
        state_hash=row["state_hash"],
        actor=ActorRef.model_validate_json(row["actor_json"]),
        created_at=_parse_dt_required(row["created_at"]),
    )


def _row_to_artifact(row: aiosqlite.Row) -> Artifact:
    return Artifact(
        id=row["id"],
        run_id=row["run_id"],
        step_run_id=row["step_run_id"],
        kind=row["kind"],
        uri=row["uri"],
        content_hash=row["content_hash"],
        size=row["size"],
        content_type=row["content_type"],
        name=row["name"],
        metadata=json.loads(row["metadata_json"]),
        created_at=_parse_dt_required(row["created_at"]),
    )


def _row_to_approval(row: aiosqlite.Row) -> Approval:
    return Approval(
        id=row["id"],
        run_id=row["run_id"],
        step_run_id=row["step_run_id"],
        status=ApprovalStatus(row["status"]),
        authority=row["authority"],
        resource=row["resource"],
        criteria=json.loads(row["criteria_json"]),
        requested_by=ActorRef.model_validate_json(row["requested_by_json"]),
        resolved_by=(
            ActorRef.model_validate_json(row["resolved_by_json"])
            if row["resolved_by_json"]
            else None
        ),
        reason=row["reason"],
        requested_at=_parse_dt_required(row["requested_at"]),
        resolved_at=_parse_dt(row["resolved_at"]),
    )


def _row_to_lease(row: aiosqlite.Row) -> Lease:
    return Lease(
        id=row["id"],
        run_id=row["run_id"],
        lease_token=row["lease_token"],
        owner=ActorRef.model_validate_json(row["owner_json"]),
        purpose=row["purpose"],
        acquired_at=_parse_dt_required(row["acquired_at"]),
        expires_at=_parse_dt_required(row["expires_at"]),
    )
