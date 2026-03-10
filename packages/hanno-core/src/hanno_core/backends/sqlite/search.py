"""SQLite FTS4 search backend — keyword-only full-text search."""

from __future__ import annotations

import contextlib
import json
import struct
from datetime import datetime
from pathlib import Path

import aiosqlite

from hanno_core.interfaces.storage import StorageBackend
from hanno_core.models import (
    Artifact,
    Event,
    Run,
    StepRun,
)
from hanno_core.models.search import EntityType, SearchMode, SearchResult

# -- DDL for FTS4 virtual tables --
# notindexed= prevents a column from being indexed but still stores it.

_CREATE_FTS_RUNS = """
CREATE VIRTUAL TABLE IF NOT EXISTS search_runs USING fts4(
    run_id, run_type, title, labels, metadata,
    notindexed=run_id
)
"""

_CREATE_FTS_EVENTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS search_events USING fts4(
    event_id, run_id, kind, payload,
    notindexed=event_id, notindexed=run_id
)
"""

_CREATE_FTS_STEPS = """
CREATE VIRTUAL TABLE IF NOT EXISTS search_steps USING fts4(
    step_id, run_id, step_name, summary, metadata,
    notindexed=step_id, notindexed=run_id
)
"""

_CREATE_FTS_ARTIFACTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS search_artifacts USING fts4(
    artifact_id, run_id, kind, name, content_text, metadata,
    notindexed=artifact_id, notindexed=run_id
)
"""

_ALL_FTS_TABLES = (
    "search_runs",
    "search_events",
    "search_steps",
    "search_artifacts",
)

_ALL_DDL = (
    _CREATE_FTS_RUNS,
    _CREATE_FTS_EVENTS,
    _CREATE_FTS_STEPS,
    _CREATE_FTS_ARTIFACTS,
)


def _flatten_dict(d: dict[str, object] | dict[str, str]) -> str:
    """Flatten a dict into searchable key=value pairs."""
    parts: list[str] = []
    for k, v in d.items():
        if isinstance(v, str):
            parts.append(f"{k}={v}")
        else:
            parts.append(f"{k}={json.dumps(v, default=str)}")
    return " ".join(parts)


def _decode_matchinfo(blob: bytes) -> list[int]:
    """Decode matchinfo('x') blob into a list of unsigned ints."""
    n = len(blob) // 4
    return list(struct.unpack(f"{n}I", blob))


def _bm25_score(matchinfo_values: list[int], num_cols: int) -> float:
    """Compute a BM25-inspired relevance score from matchinfo('x').

    Uses hits_in_this_row, hits_in_all_rows, docs_with_hits per
    (term, column) combination. Higher score = better match.
    """
    score = 0.0
    num_terms = len(matchinfo_values) // (3 * num_cols)
    for t in range(num_terms):
        for c in range(num_cols):
            idx = (t * num_cols + c) * 3
            hits_this = matchinfo_values[idx]
            hits_all = matchinfo_values[idx + 1]
            docs_with = matchinfo_values[idx + 2]
            if hits_this > 0 and docs_with > 0:
                score += hits_this / (hits_all / docs_with)
    return score


class SqliteFtsSearchBackend:
    """Keyword-only search backend using SQLite FTS4.

    Accepts either a database path (opens its own connection) or an
    existing aiosqlite.Connection (for :memory: databases in tests).
    """

    def __init__(
        self, db_path_or_conn: str | Path | aiosqlite.Connection
    ) -> None:
        if isinstance(db_path_or_conn, aiosqlite.Connection):
            self._conn: aiosqlite.Connection | None = db_path_or_conn
            self._owns_conn = False
            self._db_path: str | None = None
        else:
            self._conn = None
            self._owns_conn = True
            self._db_path = str(db_path_or_conn)

    @property
    def _db(self) -> aiosqlite.Connection:
        if self._conn is None:
            msg = "Search backend not initialized."
            raise RuntimeError(msg)
        return self._conn

    async def initialize(self) -> None:
        if self._owns_conn and self._conn is None:
            assert self._db_path is not None
            self._conn = await aiosqlite.connect(self._db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL")

        for ddl in _ALL_DDL:
            await self._db.execute(ddl)
        await self._db.commit()

    async def close(self) -> None:
        if self._owns_conn and self._conn is not None:
            await self._conn.close()
            self._conn = None

    # --- Indexing ---

    async def index_run(self, run: Run) -> None:
        await self._db.execute(
            "DELETE FROM search_runs WHERE run_id = ?", (run.id,)
        )
        await self._db.execute(
            "INSERT INTO search_runs"
            " (run_id, run_type, title, labels, metadata)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                run.id,
                run.run_type,
                run.title,
                _flatten_dict(run.labels),
                _flatten_dict(run.metadata),
            ),
        )
        await self._db.commit()

    async def index_event(self, event: Event) -> None:
        await self._db.execute(
            "DELETE FROM search_events WHERE event_id = ?",
            (event.id,),
        )
        payload = (
            json.dumps(event.payload, default=str)
            if event.payload
            else ""
        )
        await self._db.execute(
            "INSERT INTO search_events"
            " (event_id, run_id, kind, payload)"
            " VALUES (?, ?, ?, ?)",
            (event.id, event.run_id, event.kind.value, payload),
        )
        await self._db.commit()

    async def index_step_run(self, step: StepRun) -> None:
        await self._db.execute(
            "DELETE FROM search_steps WHERE step_id = ?", (step.id,)
        )
        await self._db.execute(
            "INSERT INTO search_steps"
            " (step_id, run_id, step_name, summary, metadata)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                step.id,
                step.run_id,
                step.step_name,
                step.summary or "",
                _flatten_dict(step.metadata),
            ),
        )
        await self._db.commit()

    async def index_artifact(
        self, artifact: Artifact, content: bytes | None = None
    ) -> None:
        content_text = ""
        if content is not None:
            with contextlib.suppress(Exception):
                content_text = content.decode("utf-8", errors="replace")

        await self._db.execute(
            "DELETE FROM search_artifacts WHERE artifact_id = ?",
            (artifact.id,),
        )
        await self._db.execute(
            "INSERT INTO search_artifacts"
            " (artifact_id, run_id, kind, name, content_text, metadata)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                artifact.id,
                artifact.run_id,
                artifact.kind,
                artifact.name or "",
                content_text,
                _flatten_dict(artifact.metadata),
            ),
        )
        await self._db.commit()

    async def delete_run(self, run_id: str) -> None:
        for table in _ALL_FTS_TABLES:
            await self._db.execute(
                f"DELETE FROM {table} WHERE run_id = ?", (run_id,)
            )
        await self._db.commit()

    # --- Querying ---

    async def search(
        self,
        query: str,
        *,
        mode: SearchMode = SearchMode.KEYWORD,
        entity_types: set[EntityType] | None = None,
        run_id: str | None = None,
        run_type: str | None = None,
        status: str | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
        labels: dict[str, str] | None = None,
        limit: int = 20,
    ) -> list[SearchResult]:
        if mode in (SearchMode.VECTOR, SearchMode.HYBRID):
            msg = (
                f"Search mode '{mode}' requires vector search "
                f"(not available in SQLite FTS backend)"
            )
            raise NotImplementedError(msg)

        types = entity_types or {
            EntityType.RUN,
            EntityType.EVENT,
            EntityType.STEP_RUN,
            EntityType.ARTIFACT,
        }
        results: list[SearchResult] = []

        if EntityType.RUN in types:
            results.extend(
                await self._search_runs(
                    query,
                    run_id=run_id,
                    run_type=run_type,
                    status=status,
                    after=after,
                    before=before,
                    labels=labels,
                )
            )

        if EntityType.EVENT in types:
            results.extend(
                await self._search_events(query, run_id=run_id)
            )

        if EntityType.STEP_RUN in types:
            results.extend(
                await self._search_steps(query, run_id=run_id)
            )

        if EntityType.ARTIFACT in types:
            results.extend(
                await self._search_artifacts(query, run_id=run_id)
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    async def find_similar(
        self,
        entity_type: EntityType,
        entity_id: str,
        *,
        limit: int = 10,
    ) -> list[SearchResult]:
        msg = (
            "find_similar requires vector search "
            "(not available in SQLite FTS backend)"
        )
        raise NotImplementedError(msg)

    # --- Bulk reindex ---

    async def reindex_all(self, storage: StorageBackend) -> int:
        """Rebuild the search index from storage.

        Returns count of indexed entities.
        """
        for table in _ALL_FTS_TABLES:
            await self._db.execute(f"DELETE FROM {table}")
        await self._db.commit()

        count = 0
        runs = await storage.list_runs(limit=10000)
        for run in runs:
            await self.index_run(run)
            count += 1

            events = await storage.list_events(run.id)
            for event in events:
                await self.index_event(event)
                count += 1

            steps = await storage.list_step_runs(run.id)
            for step in steps:
                await self.index_step_run(step)
                count += 1

            artifacts = await storage.list_artifacts(run.id)
            for artifact in artifacts:
                await self.index_artifact(artifact)
                count += 1

        return count

    # --- Private search helpers ---

    async def _search_runs(
        self,
        query: str,
        *,
        run_id: str | None = None,
        run_type: str | None = None,
        status: str | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
        labels: dict[str, str] | None = None,
    ) -> list[SearchResult]:
        sql = """
            SELECT run_id,
                   snippet(search_runs, '<b>', '</b>', '...', 2, 32)
                       as snip,
                   matchinfo(search_runs, 'x') as mi
            FROM search_runs
        """
        conditions = ["search_runs MATCH ?"]
        params: list[object] = [query]

        if run_id:
            conditions.append("run_id = ?")
            params.append(run_id)
        if run_type:
            conditions.append("run_type = ?")
            params.append(run_type)
        if status or after or before or labels:
            sql = sql.replace(
                "FROM search_runs",
                "FROM search_runs, runs r",
            )
            conditions.append("run_id = r.id")
            if status:
                conditions.append("r.status = ?")
                params.append(status)
            if after:
                conditions.append("r.created_at >= ?")
                params.append(after.isoformat())
            if before:
                conditions.append("r.created_at <= ?")
                params.append(before.isoformat())
            if labels:
                for k, v in labels.items():
                    conditions.append(
                        "json_extract(r.labels, ?) = ?"
                    )
                    params.append(f"$.{k}")
                    params.append(v)

        sql += " WHERE " + " AND ".join(conditions)

        return await self._execute_fts_query(
            sql, params, EntityType.RUN,
            num_cols=5, id_col=0, run_id_col=0,
        )

    async def _search_events(
        self, query: str, *, run_id: str | None = None
    ) -> list[SearchResult]:
        sql = """
            SELECT event_id, run_id,
                   snippet(search_events, '<b>', '</b>', '...', 3, 32)
                       as snip,
                   matchinfo(search_events, 'x') as mi
            FROM search_events
        """
        conditions = ["search_events MATCH ?"]
        params: list[object] = [query]

        if run_id:
            conditions.append("run_id = ?")
            params.append(run_id)

        sql += " WHERE " + " AND ".join(conditions)

        return await self._execute_fts_query(
            sql, params, EntityType.EVENT,
            num_cols=4, id_col=0, run_id_col=1,
        )

    async def _search_steps(
        self, query: str, *, run_id: str | None = None
    ) -> list[SearchResult]:
        sql = """
            SELECT step_id, run_id,
                   snippet(search_steps, '<b>', '</b>', '...', 2, 32)
                       as snip,
                   matchinfo(search_steps, 'x') as mi
            FROM search_steps
        """
        conditions = ["search_steps MATCH ?"]
        params: list[object] = [query]

        if run_id:
            conditions.append("run_id = ?")
            params.append(run_id)

        sql += " WHERE " + " AND ".join(conditions)

        return await self._execute_fts_query(
            sql, params, EntityType.STEP_RUN,
            num_cols=5, id_col=0, run_id_col=1,
        )

    async def _search_artifacts(
        self, query: str, *, run_id: str | None = None
    ) -> list[SearchResult]:
        sql = """
            SELECT artifact_id, run_id,
                   snippet(search_artifacts, '<b>', '</b>', '...', 4, 32)
                       as snip,
                   matchinfo(search_artifacts, 'x') as mi
            FROM search_artifacts
        """
        conditions = ["search_artifacts MATCH ?"]
        params: list[object] = [query]

        if run_id:
            conditions.append("run_id = ?")
            params.append(run_id)

        sql += " WHERE " + " AND ".join(conditions)

        return await self._execute_fts_query(
            sql, params, EntityType.ARTIFACT,
            num_cols=6, id_col=0, run_id_col=1,
        )

    async def _execute_fts_query(
        self,
        sql: str,
        params: list[object],
        entity_type: EntityType,
        *,
        num_cols: int,
        id_col: int = 0,
        run_id_col: int = 0,
    ) -> list[SearchResult]:
        cursor = await self._db.execute(sql, params)
        rows = await cursor.fetchall()

        if not rows:
            return []

        # Compute BM25-like scores from matchinfo
        scored: list[tuple[aiosqlite.Row, float, str]] = []
        for row in rows:
            mi_blob = row["mi"]
            mi_values = _decode_matchinfo(mi_blob)
            score = _bm25_score(mi_values, num_cols)
            snip = str(row["snip"]) if row["snip"] else ""
            scored.append((row, score, snip))

        # Normalize scores to 0-1
        max_score = max(s for _, s, _ in scored)
        if max_score == 0:
            max_score = 1.0

        results: list[SearchResult] = []
        for row, raw_score, snip in scored:
            entity_id = str(row[id_col])
            rid = str(row[run_id_col])
            score = min(1.0, raw_score / max_score)
            results.append(
                SearchResult(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    run_id=rid,
                    score=score,
                    snippet=snip,
                )
            )
        return results
