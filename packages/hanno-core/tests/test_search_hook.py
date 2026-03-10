"""Integration tests for SearchIndexerHook — end-to-end indexing via ledger operations."""

from pathlib import Path

import pytest
from hanno_core.backends.sqlite.search import SqliteFtsSearchBackend
from hanno_core.backends.sqlite.storage import SqliteStorageBackend
from hanno_core.engine.ledger import RunLedger
from hanno_core.hooks.registry import InProcessHookRegistry
from hanno_core.hooks.search import SearchIndexerHook
from hanno_core.models.identity import ActorRef
from hanno_core.models.search import EntityType
from hanno_core.stores.local_fs import LocalFsArtifactStore


@pytest.fixture
async def search_ledger(tmp_path: Path):
    """Create a ledger with search hook, using a file-based DB so both backends share data."""
    db_path = tmp_path / "test.db"

    storage = SqliteStorageBackend(db_path)
    await storage.initialize()

    search = SqliteFtsSearchBackend(db_path)
    await search.initialize()

    artifacts = LocalFsArtifactStore(tmp_path / "artifacts")

    hooks = InProcessHookRegistry()
    hooks.register(SearchIndexerHook(search, storage))

    ledger = RunLedger(storage, artifacts, hooks=hooks, search=search)
    yield ledger, search
    await search.close()
    await storage.close()


@pytest.fixture
def actor():
    return ActorRef(provider="test", identifier="agent")


class TestSearchIndexerHookIntegration:
    async def test_create_run_indexes_run(self, search_ledger, actor):
        ledger, search = search_ledger
        run = await ledger.create_run("deploy", actor=actor, title="Deploy to production")

        results = await search.search("production")
        # Should find the run and the run.created event
        run_results = [r for r in results if r.entity_type == EntityType.RUN]
        assert len(run_results) == 1
        assert run_results[0].entity_id == run.id

    async def test_add_step_indexes_step(self, search_ledger, actor):
        ledger, search = search_ledger
        run = await ledger.create_run("build", actor=actor)
        await ledger.start_run(run.id, actor=actor)
        step = await ledger.add_step(run.id, step_name="compile_sources", actor=actor)

        results = await search.search("compile_sources")
        step_results = [r for r in results if r.entity_type == EntityType.STEP_RUN]
        assert len(step_results) == 1
        assert step_results[0].entity_id == step.id

    async def test_complete_step_reindexes_with_summary(self, search_ledger, actor):
        ledger, search = search_ledger
        run = await ledger.create_run("build", actor=actor)
        await ledger.start_run(run.id, actor=actor)
        step = await ledger.add_step(run.id, step_name="test_suite", actor=actor)
        await ledger.start_step(step.id, actor=actor)
        await ledger.complete_step(
            step.id, actor=actor, summary="All 127 tests passed"
        )

        results = await search.search("127 tests passed")
        step_results = [r for r in results if r.entity_type == EntityType.STEP_RUN]
        assert len(step_results) == 1

    async def test_note_indexes_event(self, search_ledger, actor):
        ledger, search = search_ledger
        run = await ledger.create_run("debug", actor=actor)
        await ledger.start_run(run.id, actor=actor)
        await ledger.add_note(run.id, actor=actor, message="Found memory leak in connection pool")

        results = await search.search("memory leak")
        event_results = [r for r in results if r.entity_type == EntityType.EVENT]
        assert len(event_results) >= 1

    async def test_multiple_runs_searchable(self, search_ledger, actor):
        ledger, search = search_ledger
        run1 = await ledger.create_run("deploy", actor=actor, title="Deploy alpha")
        run2 = await ledger.create_run("deploy", actor=actor, title="Deploy beta")

        results = await search.search("Deploy", entity_types={EntityType.RUN})
        assert len(results) == 2
        ids = {r.entity_id for r in results}
        assert run1.id in ids
        assert run2.id in ids

    async def test_search_scoped_to_run(self, search_ledger, actor):
        ledger, search = search_ledger
        run1 = await ledger.create_run("deploy", actor=actor, title="Deploy alpha")
        await ledger.create_run("deploy", actor=actor, title="Deploy beta")

        results = await search.search(
            "Deploy", run_id=run1.id, entity_types={EntityType.RUN}
        )
        assert len(results) == 1
        assert results[0].entity_id == run1.id
