"""Postgres storage backend implementation."""

from __future__ import annotations

import asyncio
import importlib.resources
import json
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import asyncpg
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
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
    Task,
    TaskRepoLink,
    TaskStatus,
    Workspace,
    WorkspaceRepo,
    WorkspaceStatus,
)
from hanno_core.models.identity import ActorRef

from . import queries as Q


def _run_alembic_upgrade(dsn: str) -> None:
    """Run Alembic migrations synchronously (called from a thread)."""
    pkg_files = importlib.resources.files("hanno_postgres")
    ini_path = str(pkg_files / "alembic.ini")

    alembic_cfg = AlembicConfig(ini_path)
    url = dsn
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    alembic_cfg.set_main_option("sqlalchemy.url", url)
    alembic_command.upgrade(alembic_cfg, "head")


class PostgresStorageBackend:
    """Postgres implementation of the StorageBackend protocol."""

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 10) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: asyncpg.Pool | None = None

    @property
    def _db(self) -> asyncpg.Pool:
        if self._pool is None:
            msg = "Storage not initialized. Call initialize() first."
            raise RuntimeError(msg)
        return self._pool

    async def _create_pool(self) -> None:
        async def _init_conn(conn: asyncpg.Connection) -> None:
            await conn.set_type_codec(
                "jsonb",
                encoder=lambda v: json.dumps(v, default=str),
                decoder=json.loads,
                schema="pg_catalog",
            )

        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
            init=_init_conn,
        )

    async def initialize(self) -> None:
        await self._create_pool()
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            await loop.run_in_executor(executor, _run_alembic_upgrade, self._dsn)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    # --- Workspaces ---

    async def create_workspace(self, workspace: Workspace) -> Workspace:
        async with self._db.acquire() as conn:
            await conn.execute(
                Q.INSERT_WORKSPACE,
                workspace.id,
                workspace.title,
                workspace.status.value,
                [r.model_dump() for r in workspace.external_refs],
                workspace.labels,
                workspace.metadata,
                workspace.created_at,
                workspace.updated_at,
            )
        return workspace

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(Q.SELECT_WORKSPACE, workspace_id)
        if row is None:
            return None
        return _row_to_workspace(row)

    async def update_workspace(self, workspace: Workspace) -> Workspace:
        async with self._db.acquire() as conn:
            await conn.execute(
                Q.UPDATE_WORKSPACE,
                workspace.title,
                workspace.status.value,
                [r.model_dump() for r in workspace.external_refs],
                workspace.labels,
                workspace.metadata,
                workspace.updated_at,
                workspace.id,
            )
        return workspace

    async def list_workspaces(
        self,
        *,
        status: WorkspaceStatus | None = None,
        labels: dict[str, str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Workspace]:
        clauses: list[str] = []
        params: list[object] = []
        if status is not None:
            params.append(status.value)
            clauses.append(f"status = ${len(params)}")
        if labels:
            params.append(labels)
            clauses.append(f"labels_json @> ${len(params)}")

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        limit_param = len(params)
        params.append(offset)
        offset_param = len(params)
        sql = (
            f"SELECT * FROM workspaces{where} ORDER BY created_at DESC "
            f"LIMIT ${limit_param} OFFSET ${offset_param}"
        )
        async with self._db.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [_row_to_workspace(r) for r in rows]

    async def find_workspaces_by_external_ref(
        self,
        *,
        system: str,
        ref_type: str,
        ref_id: str,
        status: WorkspaceStatus | None = None,
    ) -> Sequence[Workspace]:
        clauses = ["external_refs_json @> $1::jsonb"]
        params: list[object] = [
            json.dumps([{"system": system, "ref_type": ref_type, "ref_id": ref_id}]),
        ]
        if status is not None:
            params.append(status.value)
            clauses.append(f"status = ${len(params)}")
        where = " WHERE " + " AND ".join(clauses)
        sql = f"SELECT * FROM workspaces{where} ORDER BY created_at DESC"
        async with self._db.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [_row_to_workspace(r) for r in rows]

    # --- Workspace repos ---

    async def create_workspace_repo(self, repo: WorkspaceRepo) -> WorkspaceRepo:
        async with self._db.acquire() as conn:
            await conn.execute(
                Q.INSERT_WORKSPACE_REPO,
                repo.id,
                repo.workspace_id,
                repo.vcs,
                repo.display_name,
                repo.canonical_remote,
                repo.local_path,
                repo.default_branch,
                repo.metadata,
                repo.created_at,
                repo.updated_at,
            )
        return repo

    async def get_workspace_repo(self, workspace_repo_id: str) -> WorkspaceRepo | None:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(Q.SELECT_WORKSPACE_REPO, workspace_repo_id)
        if row is None:
            return None
        return _row_to_workspace_repo(row)

    async def update_workspace_repo(self, repo: WorkspaceRepo) -> WorkspaceRepo:
        async with self._db.acquire() as conn:
            await conn.execute(
                Q.UPDATE_WORKSPACE_REPO,
                repo.vcs,
                repo.display_name,
                repo.canonical_remote,
                repo.local_path,
                repo.default_branch,
                repo.metadata,
                repo.updated_at,
                repo.id,
            )
        return repo

    async def list_workspace_repos(self, workspace_id: str) -> Sequence[WorkspaceRepo]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM workspace_repos WHERE workspace_id = $1 ORDER BY created_at ASC",
                workspace_id,
            )
        return [_row_to_workspace_repo(r) for r in rows]

    async def find_workspace_repos(
        self,
        *,
        canonical_remote: str | None = None,
        local_path: str | None = None,
        workspace_id: str | None = None,
    ) -> Sequence[WorkspaceRepo]:
        clauses: list[str] = []
        params: list[object] = []
        if workspace_id is not None:
            params.append(workspace_id)
            clauses.append(f"workspace_id = ${len(params)}")
        if canonical_remote is not None:
            params.append(canonical_remote)
            clauses.append(f"canonical_remote = ${len(params)}")
        if local_path is not None:
            params.append(local_path)
            clauses.append(f"local_path = ${len(params)}")

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM workspace_repos{where} ORDER BY created_at ASC"
        async with self._db.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [_row_to_workspace_repo(r) for r in rows]

    # --- Tasks ---

    async def create_task(self, task: Task) -> Task:
        async with self._db.acquire() as conn:
            await conn.execute(
                Q.INSERT_TASK,
                task.id,
                task.workspace_id,
                task.title,
                task.status.value,
                [r.model_dump() for r in task.external_refs],
                task.labels,
                task.metadata,
                task.created_at,
                task.updated_at,
            )
        return task

    async def get_task(self, task_id: str) -> Task | None:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(Q.SELECT_TASK, task_id)
        if row is None:
            return None
        return _row_to_task(row)

    async def update_task(self, task: Task) -> Task:
        async with self._db.acquire() as conn:
            await conn.execute(
                Q.UPDATE_TASK,
                task.title,
                task.status.value,
                [r.model_dump() for r in task.external_refs],
                task.labels,
                task.metadata,
                task.updated_at,
                task.id,
            )
        return task

    async def list_tasks(
        self,
        *,
        workspace_id: str | None = None,
        status: TaskStatus | None = None,
        labels: dict[str, str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Task]:
        clauses: list[str] = []
        params: list[object] = []
        if workspace_id is not None:
            params.append(workspace_id)
            clauses.append(f"workspace_id = ${len(params)}")
        if status is not None:
            params.append(status.value)
            clauses.append(f"status = ${len(params)}")
        if labels:
            params.append(labels)
            clauses.append(f"labels_json @> ${len(params)}")

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        limit_param = len(params)
        params.append(offset)
        offset_param = len(params)
        sql = (
            f"SELECT * FROM tasks{where} ORDER BY created_at DESC "
            f"LIMIT ${limit_param} OFFSET ${offset_param}"
        )
        async with self._db.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [_row_to_task(r) for r in rows]

    async def find_tasks_by_external_ref(
        self,
        *,
        workspace_id: str,
        system: str,
        ref_type: str,
        ref_id: str,
        status: TaskStatus | None = None,
    ) -> Sequence[Task]:
        clauses = [
            "workspace_id = $1",
            "external_refs_json @> $2::jsonb",
        ]
        params: list[object] = [
            workspace_id,
            json.dumps([{"system": system, "ref_type": ref_type, "ref_id": ref_id}]),
        ]
        if status is not None:
            params.append(status.value)
            clauses.append(f"status = ${len(params)}")
        where = " WHERE " + " AND ".join(clauses)
        sql = f"SELECT * FROM tasks{where} ORDER BY created_at DESC"
        async with self._db.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [_row_to_task(r) for r in rows]

    async def create_task_repo_link(self, link: TaskRepoLink) -> TaskRepoLink:
        async with self._db.acquire() as conn:
            await conn.execute(
                Q.INSERT_TASK_REPO_LINK,
                link.id,
                link.task_id,
                link.workspace_repo_id,
                link.created_at,
            )
        return link

    async def list_task_repo_links(self, task_id: str) -> Sequence[TaskRepoLink]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM task_repo_links WHERE task_id = $1 ORDER BY created_at ASC",
                task_id,
            )
        return [_row_to_task_repo_link(r) for r in rows]

    async def has_task_repo_link(self, task_id: str, workspace_repo_id: str) -> bool:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM task_repo_links WHERE task_id = $1 AND workspace_repo_id = $2",
                task_id,
                workspace_repo_id,
            )
        return row is not None

    # --- Runs ---

    async def create_run(self, run: Run) -> Run:
        async with self._db.acquire() as conn:
            await conn.execute(
                Q.INSERT_RUN,
                run.id,
                run.workspace_id,
                run.task_id,
                run.workspace_repo_id,
                run.run_type,
                run.status.value,
                run.title,
                [r.model_dump() for r in run.external_refs],
                run.labels,
                run.metadata,
                run.created_at,
                run.updated_at,
            )
        return run

    async def get_run(self, run_id: str) -> Run | None:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(Q.SELECT_RUN, run_id)
        if row is None:
            return None
        return _row_to_run(row)

    async def list_runs(
        self,
        *,
        status: RunStatus | None = None,
        run_type: str | None = None,
        workspace_id: str | None = None,
        task_id: str | None = None,
        workspace_repo_id: str | None = None,
        labels: dict[str, str] | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Run]:
        clauses: list[str] = []
        params: list[object] = []
        if status is not None:
            params.append(status.value)
            clauses.append(f"status = ${len(params)}")
        if run_type is not None:
            params.append(run_type)
            clauses.append(f"run_type = ${len(params)}")
        if workspace_id is not None:
            params.append(workspace_id)
            clauses.append(f"workspace_id = ${len(params)}")
        if task_id is not None:
            params.append(task_id)
            clauses.append(f"task_id = ${len(params)}")
        if workspace_repo_id is not None:
            params.append(workspace_repo_id)
            clauses.append(f"workspace_repo_id = ${len(params)}")
        if labels:
            params.append(labels)
            clauses.append(f"labels_json @> ${len(params)}")

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        limit_param = len(params)
        params.append(offset)
        offset_param = len(params)
        sql = (
            f"SELECT * FROM runs{where} ORDER BY created_at DESC "
            f"LIMIT ${limit_param} OFFSET ${offset_param}"
        )
        async with self._db.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [_row_to_run(r) for r in rows]

    async def update_run(self, run: Run) -> Run:
        async with self._db.acquire() as conn:
            await conn.execute(
                Q.UPDATE_RUN,
                run.workspace_id,
                run.task_id,
                run.workspace_repo_id,
                run.status.value,
                run.title,
                [r.model_dump() for r in run.external_refs],
                run.labels,
                run.metadata,
                run.updated_at,
                run.id,
            )
        return run

    async def find_runs_by_external_ref(
        self,
        *,
        system: str,
        ref_type: str,
        ref_id: str,
        status: RunStatus | None = None,
    ) -> Sequence[Run]:
        clauses = ["external_refs_json @> $1::jsonb"]
        params: list[object] = [
            json.dumps([{"system": system, "ref_type": ref_type, "ref_id": ref_id}]),
        ]
        if status is not None:
            params.append(status.value)
            clauses.append(f"status = ${len(params)}")
        where = " WHERE " + " AND ".join(clauses)
        sql = f"SELECT * FROM runs{where} ORDER BY created_at DESC"
        async with self._db.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [_row_to_run(r) for r in rows]

    # --- Events ---

    async def append_event(self, event: Event) -> Event:
        async with self._db.acquire() as conn:
            await conn.execute(
                Q.INSERT_EVENT,
                event.id,
                event.run_id,
                event.sequence,
                event.kind.value,
                event.actor.model_dump(),
                event.payload,
                event.step_run_id,
                event.parent_event_id,
                event.trace_id,
                event.span_id,
                event.timestamp,
            )
        return event

    async def get_event(self, event_id: str) -> Event | None:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(Q.SELECT_EVENT, event_id)
        if row is None:
            return None
        return _row_to_event(row)

    async def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        kinds: Sequence[EventKind] | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
        limit: int | None = None,
    ) -> Sequence[Event]:
        clauses = ["run_id = $1", "sequence > $2"]
        params: list[object] = [run_id, after_sequence]

        if kinds:
            start = len(params) + 1
            placeholders = ", ".join(f"${start + i}" for i in range(len(kinds)))
            clauses.append(f"kind IN ({placeholders})")
            params.extend(k.value for k in kinds)

        if after is not None:
            params.append(after)
            clauses.append(f"timestamp > ${len(params)}")

        if before is not None:
            params.append(before)
            clauses.append(f"timestamp < ${len(params)}")

        where = " AND ".join(clauses)
        sql = f"SELECT * FROM events WHERE {where} ORDER BY sequence ASC"
        if limit is not None:
            params.append(limit)
            sql += f" LIMIT ${len(params)}"

        async with self._db.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [_row_to_event(r) for r in rows]

    # --- Steps ---

    async def create_step_run(self, step: StepRun) -> StepRun:
        async with self._db.acquire() as conn:
            await conn.execute(
                Q.INSERT_STEP_RUN,
                step.id,
                step.run_id,
                step.step_name,
                step.status.value,
                step.iteration,
                step.parent_step_run_id,
                step.started_at,
                step.ended_at,
                step.summary,
                step.metadata,
                step.created_at,
            )
        return step

    async def get_step_run(self, step_run_id: str) -> StepRun | None:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(Q.SELECT_STEP_RUN, step_run_id)
        if row is None:
            return None
        return _row_to_step_run(row)

    async def list_step_runs(self, run_id: str) -> Sequence[StepRun]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM step_runs WHERE run_id = $1 ORDER BY created_at ASC",
                run_id,
            )
        return [_row_to_step_run(r) for r in rows]

    async def update_step_run(self, step: StepRun) -> StepRun:
        async with self._db.acquire() as conn:
            await conn.execute(
                Q.UPDATE_STEP_RUN,
                step.status.value,
                step.started_at,
                step.ended_at,
                step.summary,
                step.metadata,
                step.id,
            )
        return step

    # --- Edges ---

    async def create_edge(self, edge: Edge) -> Edge:
        async with self._db.acquire() as conn:
            await conn.execute(
                Q.INSERT_EDGE,
                edge.id,
                edge.run_id,
                edge.from_step_run_id,
                edge.to_step_run_id,
                edge.kind.value,
                edge.metadata,
            )
        return edge

    async def list_edges(self, run_id: str) -> Sequence[Edge]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM edges WHERE run_id = $1", run_id)
        return [_row_to_edge(r) for r in rows]

    # --- State Versions ---

    async def append_state_version(self, sv: StateVersion) -> StateVersion:
        async with self._db.acquire() as conn:
            await conn.execute(
                Q.INSERT_STATE_VERSION,
                sv.id,
                sv.run_id,
                sv.sequence,
                sv.prev_state_version_id,
                sv.state_ref,
                sv.state_hash,
                sv.actor.model_dump(),
                sv.created_at,
            )
        return sv

    async def get_latest_state_version(self, run_id: str) -> StateVersion | None:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM state_versions WHERE run_id = $1 "
                "ORDER BY sequence DESC LIMIT 1",
                run_id,
            )
        if row is None:
            return None
        return _row_to_state_version(row)

    async def list_state_versions(self, run_id: str) -> Sequence[StateVersion]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM state_versions WHERE run_id = $1 ORDER BY sequence ASC",
                run_id,
            )
        return [_row_to_state_version(r) for r in rows]

    # --- Artifacts ---

    async def create_artifact(self, artifact: Artifact) -> Artifact:
        async with self._db.acquire() as conn:
            await conn.execute(
                Q.INSERT_ARTIFACT,
                artifact.id,
                artifact.run_id,
                artifact.step_run_id,
                artifact.kind,
                artifact.uri,
                artifact.content_hash,
                artifact.size,
                artifact.content_type,
                artifact.name,
                artifact.metadata,
                artifact.created_at,
            )
        return artifact

    async def get_artifact(self, artifact_id: str) -> Artifact | None:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(Q.SELECT_ARTIFACT, artifact_id)
        if row is None:
            return None
        return _row_to_artifact(row)

    async def list_artifacts(
        self,
        run_id: str,
        *,
        step_run_id: str | None = None,
        kind: str | None = None,
    ) -> Sequence[Artifact]:
        clauses = ["run_id = $1"]
        params: list[object] = [run_id]
        if step_run_id is not None:
            params.append(step_run_id)
            clauses.append(f"step_run_id = ${len(params)}")
        if kind is not None:
            params.append(kind)
            clauses.append(f"kind = ${len(params)}")

        sql = f"SELECT * FROM artifacts WHERE {' AND '.join(clauses)} ORDER BY created_at ASC"
        async with self._db.acquire() as conn:
            rows = await conn.fetch(sql, *params)
        return [_row_to_artifact(r) for r in rows]

    # --- Approvals ---

    async def create_approval(self, approval: Approval) -> Approval:
        async with self._db.acquire() as conn:
            await conn.execute(
                Q.INSERT_APPROVAL,
                approval.id,
                approval.run_id,
                approval.step_run_id,
                approval.status.value,
                approval.authority,
                approval.resource,
                approval.criteria,
                approval.requested_by.model_dump(),
                approval.resolved_by.model_dump() if approval.resolved_by else None,
                approval.reason,
                approval.requested_at,
                approval.resolved_at,
            )
        return approval

    async def get_approval(self, approval_id: str) -> Approval | None:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(Q.SELECT_APPROVAL, approval_id)
        if row is None:
            return None
        return _row_to_approval(row)

    async def list_approvals(
        self, run_id: str, *, status: ApprovalStatus | None = None
    ) -> Sequence[Approval]:
        async with self._db.acquire() as conn:
            if status is not None:
                rows = await conn.fetch(
                    (
                        "SELECT * FROM approvals WHERE run_id = $1 AND status = $2 "
                        "ORDER BY requested_at ASC"
                    ),
                    run_id,
                    status.value,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM approvals WHERE run_id = $1 ORDER BY requested_at ASC",
                    run_id,
                )
        return [_row_to_approval(r) for r in rows]

    async def update_approval(self, approval: Approval) -> Approval:
        async with self._db.acquire() as conn:
            await conn.execute(
                Q.UPDATE_APPROVAL,
                approval.status.value,
                approval.resolved_by.model_dump() if approval.resolved_by else None,
                approval.reason,
                approval.resolved_at,
                approval.id,
            )
        return approval

    # --- Leases ---

    async def create_lease(self, lease: Lease) -> Lease:
        async with self._db.acquire() as conn:
            await conn.execute(
                Q.INSERT_LEASE,
                lease.id,
                lease.run_id,
                lease.lease_token,
                lease.owner.model_dump(),
                lease.purpose,
                lease.acquired_at,
                lease.expires_at,
            )
        return lease

    async def get_lease(self, lease_id: str) -> Lease | None:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(Q.SELECT_LEASE, lease_id)
        if row is None:
            return None
        return _row_to_lease(row)

    async def list_active_leases(self, run_id: str) -> Sequence[Lease]:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM leases WHERE run_id = $1 AND expires_at > NOW()",
                run_id,
            )
        return [_row_to_lease(r) for r in rows]

    async def delete_lease(self, lease_id: str) -> None:
        async with self._db.acquire() as conn:
            await conn.execute(Q.DELETE_LEASE, lease_id)

    async def expire_stale_leases(self) -> int:
        async with self._db.acquire() as conn:
            rows = await conn.fetch(Q.DELETE_EXPIRED_LEASES)
        return len(rows)

    # --- Sequence Counter ---

    async def next_sequence(self, run_id: str) -> int:
        async with self._db.acquire() as conn:
            row = await conn.fetchrow(Q.UPSERT_SEQUENCE, run_id)
        return row["current_seq"]  # type: ignore[no-any-return]


def _ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _ensure_utc_required(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _parse_actor(val: dict[str, object]) -> ActorRef:
    return ActorRef.model_validate(val)


def _row_to_workspace(row: asyncpg.Record) -> Workspace:
    return Workspace(
        id=row["id"],
        title=row["title"],
        status=WorkspaceStatus(row["status"]),
        external_refs=row["external_refs_json"],
        labels=row["labels_json"],
        metadata=row["metadata_json"],
        created_at=_ensure_utc_required(row["created_at"]),
        updated_at=_ensure_utc_required(row["updated_at"]),
    )


def _row_to_workspace_repo(row: asyncpg.Record) -> WorkspaceRepo:
    return WorkspaceRepo(
        id=row["id"],
        workspace_id=row["workspace_id"],
        vcs=row["vcs"],
        display_name=row["display_name"],
        canonical_remote=row["canonical_remote"],
        local_path=row["local_path"],
        default_branch=row["default_branch"],
        metadata=row["metadata_json"],
        created_at=_ensure_utc_required(row["created_at"]),
        updated_at=_ensure_utc_required(row["updated_at"]),
    )


def _row_to_task(row: asyncpg.Record) -> Task:
    return Task(
        id=row["id"],
        workspace_id=row["workspace_id"],
        title=row["title"],
        status=TaskStatus(row["status"]),
        external_refs=row["external_refs_json"],
        labels=row["labels_json"],
        metadata=row["metadata_json"],
        created_at=_ensure_utc_required(row["created_at"]),
        updated_at=_ensure_utc_required(row["updated_at"]),
    )


def _row_to_task_repo_link(row: asyncpg.Record) -> TaskRepoLink:
    return TaskRepoLink(
        id=row["id"],
        task_id=row["task_id"],
        workspace_repo_id=row["workspace_repo_id"],
        created_at=_ensure_utc_required(row["created_at"]),
    )


def _row_to_run(row: asyncpg.Record) -> Run:
    return Run(
        id=row["id"],
        workspace_id=row["workspace_id"],
        task_id=row["task_id"],
        workspace_repo_id=row["workspace_repo_id"],
        run_type=row["run_type"],
        status=RunStatus(row["status"]),
        title=row["title"],
        external_refs=row["external_refs_json"],
        labels=row["labels_json"],
        metadata=row["metadata_json"],
        created_at=_ensure_utc_required(row["created_at"]),
        updated_at=_ensure_utc_required(row["updated_at"]),
    )


def _row_to_event(row: asyncpg.Record) -> Event:
    return Event(
        id=row["id"],
        run_id=row["run_id"],
        sequence=row["sequence"],
        kind=EventKind(row["kind"]),
        actor=_parse_actor(row["actor_json"]),
        payload=row["payload_json"],
        step_run_id=row["step_run_id"],
        parent_event_id=row["parent_event_id"],
        trace_id=row["trace_id"],
        span_id=row["span_id"],
        timestamp=_ensure_utc_required(row["timestamp"]),
    )


def _row_to_step_run(row: asyncpg.Record) -> StepRun:
    return StepRun(
        id=row["id"],
        run_id=row["run_id"],
        step_name=row["step_name"],
        status=StepRunStatus(row["status"]),
        iteration=row["iteration"],
        parent_step_run_id=row["parent_step_run_id"],
        started_at=_ensure_utc(row["started_at"]),
        ended_at=_ensure_utc(row["ended_at"]),
        summary=row["summary"],
        metadata=row["metadata_json"],
        created_at=_ensure_utc_required(row["created_at"]),
    )


def _row_to_edge(row: asyncpg.Record) -> Edge:
    return Edge(
        id=row["id"],
        run_id=row["run_id"],
        from_step_run_id=row["from_step_run_id"],
        to_step_run_id=row["to_step_run_id"],
        kind=EdgeKind(row["kind"]),
        metadata=row["metadata_json"],
    )


def _row_to_state_version(row: asyncpg.Record) -> StateVersion:
    return StateVersion(
        id=row["id"],
        run_id=row["run_id"],
        sequence=row["sequence"],
        prev_state_version_id=row["prev_state_version_id"],
        state_ref=row["state_ref"],
        state_hash=row["state_hash"],
        actor=_parse_actor(row["actor_json"]),
        created_at=_ensure_utc_required(row["created_at"]),
    )


def _row_to_artifact(row: asyncpg.Record) -> Artifact:
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
        metadata=row["metadata_json"],
        created_at=_ensure_utc_required(row["created_at"]),
    )


def _row_to_approval(row: asyncpg.Record) -> Approval:
    return Approval(
        id=row["id"],
        run_id=row["run_id"],
        step_run_id=row["step_run_id"],
        status=ApprovalStatus(row["status"]),
        authority=row["authority"],
        resource=row["resource"],
        criteria=row["criteria_json"],
        requested_by=_parse_actor(row["requested_by_json"]),
        resolved_by=(
            _parse_actor(row["resolved_by_json"])
            if row["resolved_by_json"] is not None
            else None
        ),
        reason=row["reason"],
        requested_at=_ensure_utc_required(row["requested_at"]),
        resolved_at=_ensure_utc(row["resolved_at"]),
    )


def _row_to_lease(row: asyncpg.Record) -> Lease:
    return Lease(
        id=row["id"],
        run_id=row["run_id"],
        lease_token=row["lease_token"],
        owner=_parse_actor(row["owner_json"]),
        purpose=row["purpose"],
        acquired_at=_ensure_utc_required(row["acquired_at"]),
        expires_at=_ensure_utc_required(row["expires_at"]),
    )
