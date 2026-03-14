"""Tests for the SQLite FTS4 search backend."""

import aiosqlite
import pytest
from hanno_core.backends.sqlite.search import SqliteFtsSearchBackend
from hanno_core.models import (
    Artifact,
    Event,
    EventKind,
    Run,
    StepRun,
    StepRunStatus,
)
from hanno_core.models.identity import ActorRef
from hanno_core.models.search import EntityType, SearchMode


@pytest.fixture
async def conn():
    """Shared in-memory connection for FTS tests."""
    c = await aiosqlite.connect(":memory:")
    c.row_factory = aiosqlite.Row
    yield c
    await c.close()


@pytest.fixture
async def search(conn):
    backend = SqliteFtsSearchBackend(conn)
    await backend.initialize()
    return backend


@pytest.fixture
def actor():
    return ActorRef(provider="test", identifier="agent")


def _make_run(
    *,
    run_id: str = "run-1",
    workspace_id: str = "ws-1",
    title: str = "Test Run",
    run_type: str = "deploy",
    labels: dict | None = None,
) -> Run:
    return Run(
        id=run_id,
        workspace_id=workspace_id,
        run_type=run_type,
        title=title,
        labels=labels or {},
        metadata={},
    )


def _make_event(
    *,
    event_id: str = "evt-1",
    run_id: str = "run-1",
    kind: EventKind = EventKind.NOTE,
    payload: dict | None = None,
) -> Event:
    return Event(
        id=event_id,
        run_id=run_id,
        sequence=1,
        kind=kind,
        actor=ActorRef(provider="test", identifier="agent"),
        payload=payload or {},
    )


def _make_step(
    *,
    step_id: str = "step-1",
    run_id: str = "run-1",
    step_name: str = "build",
    summary: str = "",
) -> StepRun:
    return StepRun(
        id=step_id,
        run_id=run_id,
        step_name=step_name,
        status=StepRunStatus.QUEUED,
        summary=summary,
    )


def _make_artifact(
    *,
    artifact_id: str = "art-1",
    run_id: str = "run-1",
    kind: str = "log",
    name: str = "build.log",
) -> Artifact:
    return Artifact(
        id=artifact_id,
        run_id=run_id,
        kind=kind,
        name=name,
        uri="file:///tmp/build.log",
        content_hash="abc123",
        size=42,
    )


class TestIndexAndSearch:
    async def test_index_and_search_run(self, search):
        run = _make_run(title="Deploy production server")
        await search.index_run(run)

        results = await search.search("production")
        assert len(results) == 1
        assert results[0].entity_type == EntityType.RUN
        assert results[0].entity_id == "run-1"
        assert results[0].run_id == "run-1"
        assert 0 < results[0].score <= 1.0

    async def test_index_and_search_event(self, search):
        event = _make_event(
            payload={"message": "Authentication failed for user admin"}
        )
        await search.index_event(event)

        results = await search.search("Authentication failed")
        assert len(results) == 1
        assert results[0].entity_type == EntityType.EVENT
        assert results[0].entity_id == "evt-1"

    async def test_index_and_search_step(self, search):
        step = _make_step(
            step_name="compile", summary="Compiled 42 source files"
        )
        await search.index_step_run(step)

        results = await search.search("compile")
        assert len(results) == 1
        assert results[0].entity_type == EntityType.STEP_RUN

    async def test_index_and_search_artifact(self, search):
        artifact = _make_artifact(name="error-report.txt")
        await search.index_artifact(
            artifact, content=b"NullPointerException at line 42"
        )

        results = await search.search("NullPointerException")
        assert len(results) == 1
        assert results[0].entity_type == EntityType.ARTIFACT

    async def test_search_no_results(self, search):
        run = _make_run(title="Deploy server")
        await search.index_run(run)

        results = await search.search("xyznonexistent")
        assert results == []


class TestFilters:
    async def test_filter_by_entity_type(self, search):
        await search.index_run(_make_run(title="deploy production"))
        await search.index_event(
            _make_event(payload={"msg": "deploy started"})
        )

        # Only runs
        results = await search.search(
            "deploy", entity_types={EntityType.RUN}
        )
        assert all(r.entity_type == EntityType.RUN for r in results)

        # Only events
        results = await search.search(
            "deploy", entity_types={EntityType.EVENT}
        )
        assert all(
            r.entity_type == EntityType.EVENT for r in results
        )

    async def test_filter_by_run_id(self, search):
        await search.index_run(
            _make_run(run_id="run-1", title="deploy alpha")
        )
        await search.index_run(
            _make_run(run_id="run-2", title="deploy beta")
        )

        results = await search.search("deploy", run_id="run-1")
        assert len(results) == 1
        assert results[0].entity_id == "run-1"

    async def test_limit(self, search):
        for i in range(10):
            await search.index_run(
                _make_run(run_id=f"run-{i}", title=f"deploy server {i}")
            )

        results = await search.search("deploy", limit=3)
        assert len(results) == 3


class TestUpdateAndDelete:
    async def test_reindex_updates_existing(self, search):
        run = _make_run(title="old title deploy")
        await search.index_run(run)

        results = await search.search("old title")
        assert len(results) == 1

        # Update with new title
        updated = _make_run(title="new title release")
        await search.index_run(updated)

        results = await search.search("old title")
        assert len(results) == 0

        results = await search.search("new title")
        assert len(results) == 1

    async def test_delete_run(self, search):
        await search.index_run(
            _make_run(run_id="run-1", title="deploy alpha")
        )
        await search.index_event(
            _make_event(
                event_id="evt-1",
                run_id="run-1",
                payload={"msg": "alpha started"},
            )
        )

        results = await search.search("alpha")
        assert len(results) == 2

        await search.delete_run("run-1")

        results = await search.search("alpha")
        assert len(results) == 0


class TestScoring:
    async def test_scores_between_0_and_1(self, search):
        for i in range(5):
            await search.index_run(
                _make_run(
                    run_id=f"run-{i}",
                    title=f"deploy server number {i}",
                )
            )

        results = await search.search("deploy server")
        for r in results:
            assert 0 < r.score <= 1.0

    async def test_best_match_has_highest_score(self, search):
        await search.index_run(
            _make_run(run_id="run-exact", title="deploy production")
        )
        await search.index_run(
            _make_run(
                run_id="run-partial", title="the server will deploy"
            )
        )

        results = await search.search("deploy production")
        assert len(results) >= 1
        # Best match should be first
        assert results[0].entity_id == "run-exact"


class TestUnsupportedModes:
    async def test_vector_mode_raises(self, search):
        with pytest.raises(NotImplementedError, match="vector search"):
            await search.search("test", mode=SearchMode.VECTOR)

    async def test_hybrid_mode_raises(self, search):
        with pytest.raises(NotImplementedError, match="vector search"):
            await search.search("test", mode=SearchMode.HYBRID)

    async def test_find_similar_raises(self, search):
        with pytest.raises(NotImplementedError, match="vector search"):
            await search.find_similar(EntityType.RUN, "run-1")
