# Hanno — Workflow Ledger Implementation Plan

## Context

Hanno is a lightweight, implementation-agnostic workflow ledger: an append-only event log with versioned state snapshots, pluggable storage, pluggable artifact stores, and optional indexing/search. It tracks agent execution state (step progress, loops, approvals, blockers, artifacts) without becoming a full workflow engine.

This plan breaks the design document into implementable milestones for a Python monorepo using uv workspaces.

## Decisions

- **Language**: Python 3.12+
- **Package manager**: uv with workspaces
- **Structure**: Monorepo, multiple packages (`packages/*`)
- **First backend**: SQLite (WAL mode) via aiosqlite
- **Models**: Pydantic v2
- **IDs**: ULIDs (time-sortable, 26 chars)
- **Interfaces**: `typing.Protocol` (structural subtyping)
- **CLI**: Typer + Rich
- **Testing**: pytest + pytest-asyncio
- **Linting**: ruff + mypy
- **Build**: hatchling

## Repository Layout

```
hanno/
  pyproject.toml                          # workspace root (virtual)
  .gitignore
  .github/workflows/ci.yml
  packages/
    hanno-core/
      pyproject.toml
      src/hanno_core/
        __init__.py
        models/                           # pydantic v2 domain models
          __init__.py
          enums.py                        # RunStatus, StepRunStatus, EdgeKind, EventKind
          identity.py                     # ActorRef
          run.py                          # Run
          step.py                         # StepRun
          event.py                        # Event
          edge.py                         # Edge
          artifact.py                     # Artifact, ArtifactRef
          approval.py                     # Approval, ApprovalRequest
          lease.py                        # Lease
          state.py                        # StateVersion
        interfaces/                       # Protocol definitions
          __init__.py
          storage.py                      # StorageBackend
          artifacts.py                    # ArtifactStore
          hooks.py                        # Hook, HookRegistry
          search.py                       # SearchIndexer
          identity.py                     # IdentityProvider
        engine/                           # core ledger logic
          __init__.py
          ledger.py                       # RunLedger (main API)
          projections.py                  # event replay → state
          compaction.py                   # transcript bundles, AARs
        backends/
          sqlite/
            __init__.py
            storage.py                    # SqliteStorageBackend
            migrations.py                # DDL + migration runner
            queries.py                   # SQL constants
        stores/
          __init__.py
          local_fs.py                     # LocalFsArtifactStore (SHA-256 content-addressed)
        hooks/
          __init__.py
          registry.py                     # InProcessHookRegistry
      tests/
        conftest.py
        test_models.py
        test_sqlite_storage.py
        test_local_fs_store.py
        test_ledger.py
        test_projections.py
        test_hooks.py
        fixtures/
          factories.py                    # test data factories

    hanno-cli/
      pyproject.toml
      src/hanno_cli/
        __init__.py
        main.py                           # typer app entry
        config.py                         # ~/.hanno/ config, env vars
        formatting.py                     # rich output helpers
        commands/
          __init__.py
          run.py                          # run create/list/show/start/cancel
          step.py                         # step add/start/complete/fail/list
          event.py                        # event list/show
          artifact.py                     # artifact attach/download/list
          approval.py                     # approval request/grant/deny/list
      tests/
        conftest.py
        test_commands.py

    hanno-mcp/
      pyproject.toml
      src/hanno_mcp/
        __init__.py
        server.py                         # FastMCP server
        tools/
          __init__.py
          runs.py
          steps.py
          events.py
          artifacts.py
          approvals.py
      tests/
        conftest.py
        test_tools.py

    hanno-postgres/                       # (Milestone D — future)
      pyproject.toml
      src/hanno_postgres/
        __init__.py
        storage.py
        migrations.py
        queries.py
      tests/
        conftest.py
        test_postgres_storage.py
```

## Milestone Dependency Graph

```
M0 (Scaffolding)
 |
M-A (Core + SQLite + Local FS)
 |
 +--------+--------+
 |        |        |
M-B     M-C      M-D
(CLI)   (MCP)   (Postgres)
 |        |
 +--------+
 |
M-E (Search — optional)
```

B, C, D are independent and parallelizable after A.

---

## Milestone 0: Project Scaffolding

**Goal**: Buildable monorepo, `uv sync --all-packages && uv run pytest` passes.

### Tasks

1. **Create workspace root `pyproject.toml`** — virtual workspace, dev deps (pytest, pytest-asyncio, pytest-cov, ruff, mypy)
2. **Create `.gitignore`** — Python standard + `.venv`, `*.db`, `.ruff_cache`, `.mypy_cache`, `dist/`
3. **Create `packages/hanno-core/pyproject.toml`** — deps: pydantic>=2.10, aiosqlite>=0.21, python-ulid>=3.0
4. **Create `packages/hanno-cli/pyproject.toml`** — deps: hanno-core (workspace), typer[all]>=0.15, rich>=13.0; script entry `hanno`
5. **Create `packages/hanno-mcp/pyproject.toml`** — deps: hanno-core (workspace), mcp>=1.2
6. **Create `packages/hanno-postgres/pyproject.toml`** — deps: hanno-core (workspace), asyncpg>=0.30
7. **Create `__init__.py` stubs** for all packages
8. **Create `.github/workflows/ci.yml`** — uv install, ruff check, mypy, pytest; matrix Python 3.12+3.13
9. **Verify**: `uv sync --all-packages` succeeds, `uv run pytest` reports 0 tests collected

---

## Milestone A: Core Ledger (SQLite + Local FS)

**Goal**: Fully functional Python library for event-sourced workflow tracking.

### A.1 — Domain Models

Create pydantic v2 models in `packages/hanno-core/src/hanno_core/models/`:

| File | Models | Notes |
|------|--------|-------|
| `enums.py` | `RunStatus`, `StepRunStatus`, `EdgeKind`, `EventKind` | StrEnum |
| `identity.py` | `ActorRef` | provider + identifier + display_name + metadata |
| `run.py` | `Run` | ULID id, workflow_name, status, labels, metadata, timestamps |
| `step.py` | `StepRun` | ULID id, run_id, step_name, iteration, status, parent_step_run_id, summary, metadata |
| `event.py` | `Event` | ULID id, run_id, sequence, kind, actor, payload, timestamps, otel fields |
| `edge.py` | `Edge` | from_step_run_id, to_step_run_id, kind |
| `state.py` | `StateVersion` | run_id, version, state_ref, state_hash, created_at |
| `artifact.py` | `Artifact`, `ArtifactRef` | id, run_id, kind, uri, hash, size, content_type, metadata |
| `approval.py` | `Approval` | id, run_id, step_run_id, status, authority, criteria, actor |
| `lease.py` | `Lease` | id, run_id, lease_token, owner, purpose, expires_at |
| `__init__.py` | Re-exports | Public API surface |

Tests: `test_models.py` — construction, serialization, validation, defaults.

### A.2 — Interfaces

Create Protocol classes in `packages/hanno-core/src/hanno_core/interfaces/`:

| File | Protocol | Key Methods |
|------|----------|-------------|
| `storage.py` | `StorageBackend` | initialize, close, CRUD for runs/events/steps/edges/leases/state_versions |
| `artifacts.py` | `ArtifactStore` | store, retrieve, exists, delete |
| `hooks.py` | `Hook`, `HookRegistry` | on_event_appended, on_compaction, on_run_completed; register |
| `search.py` | `SearchIndexer` | ingest_document, delete_run |
| `identity.py` | `IdentityProvider` | normalize(actor_ref) → canonical_id |

All async. All use Protocol (structural subtyping).

### A.3 — SQLite Storage Backend

`packages/hanno-core/src/hanno_core/backends/sqlite/`

1. **`migrations.py`** — DDL for all tables (runs, events, step_runs, edges, leases, state_versions, artifacts, approvals, schema_migrations). Forward-only versioned migrations.
2. **`queries.py`** — Named SQL constants, parameterized.
3. **`storage.py`** — `SqliteStorageBackend` implementing `StorageBackend`:
   - Init: `aiosqlite.connect()`, WAL mode, FK enforcement
   - Events: append with `UNIQUE(run_id, sequence)` enforcement
   - Runs/steps: standard CRUD with JSON columns
   - Leases: TTL-based with expiry sweep
   - State versions: append-only, latest pointer

Tests: `test_sqlite_storage.py` — full CRUD, sequence enforcement, concurrent reads, WAL verification. Uses `:memory:`.

### A.4 — Local FS Artifact Store

`packages/hanno-core/src/hanno_core/stores/local_fs.py`

- Content-addressed: `{root}/{sha256[:2]}/{sha256[2:]}.blob`
- Metadata sidecar: `.meta.json` alongside blob
- Deduplication via hash check before write

Tests: `test_local_fs_store.py` — store/retrieve/dedup/delete, uses `tmp_path`.

### A.5 — Engine (Ledger + Projections + Compaction)

`packages/hanno-core/src/hanno_core/engine/`

1. **`ledger.py`** — `RunLedger` class: the main API.
   - Composes StorageBackend + ArtifactStore + HookRegistry
   - Methods: create_run, start_run, add_step, start_step, complete_step, fail_step, attach_artifact, request_approval, grant/deny_approval, acquire/release_lease, get_run_state, get_transcript
   - Each mutation: validate preconditions → append event → update projection → fire hooks

2. **`projections.py`** — Pure functions: `project_run_state(events) → StateVersion`
   - Deterministic, side-effect-free
   - Status transition validation

3. **`compaction.py`** — Generate transcript bundles (JSONL) and AAR summaries

Tests: `test_ledger.py` (full lifecycle), `test_projections.py` (idempotency, invalid transitions).

### A.6 — Hook Registry

`packages/hanno-core/src/hanno_core/hooks/registry.py`

- `InProcessHookRegistry`: async callbacks keyed by event kind
- Wire into RunLedger

Tests: `test_hooks.py` — verify hooks fire on event append.

### A deliverable

```python
from hanno_core.engine.ledger import RunLedger
from hanno_core.backends.sqlite.storage import SqliteStorageBackend
from hanno_core.stores.local_fs import LocalFsArtifactStore
from hanno_core.models.identity import ActorRef

storage = SqliteStorageBackend("./hanno.db")
artifacts = LocalFsArtifactStore(Path("./artifacts"))
await storage.initialize()
ledger = RunLedger(storage, artifacts)
actor = ActorRef(provider="local", identifier="steve")

run = await ledger.create_run("deploy-pipeline", actor=actor)
step = await ledger.add_step(run.id, name="build", actor=actor)
await ledger.start_step(step.id, actor=actor)
await ledger.complete_step(step.id, actor=actor, output={"image": "sha256:abc"})
```

---

## Milestone B: CLI (hanno-cli)

**Goal**: `hanno` command for managing runs, steps, events, artifacts, approvals.

1. **Config** (`config.py`): defaults `~/.hanno/hanno.db` + `~/.hanno/artifacts/`; env var overrides
2. **Commands**: run (create/list/show/start/cancel), step (add/start/complete/fail/list), event (list/show), artifact (attach/download/list), approval (request/grant/deny/list)
3. **Formatting** (`formatting.py`): Rich tables/trees; `--json` flag on all commands
4. **Tests**: typer CliRunner integration tests

---

## Milestone C: MCP Server (hanno-mcp)

**Goal**: MCP tool surface for Claude Code / Codex CLI integration.

1. **Server** (`server.py`): FastMCP, stdio transport
2. **Tools**: runs, steps, events, artifacts, approvals — map 1:1 to RunLedger API
3. **Resources**: `hanno://runs/{run_id}`, `hanno://runs/{run_id}/transcript`
4. **Config**: same env vars as CLI
5. **Tests**: MCP SDK test client

---

## Milestone D: Postgres Backend (hanno-postgres) — future

1. **`storage.py`**: asyncpg, JSONB columns, `FOR UPDATE SKIP LOCKED` for leases
2. **`migrations.py`**: raw SQL, forward-only
3. **Conformance tests**: parameterized fixtures run same test suite against SQLite + Postgres

---

## Milestone E: Search (optional) — future

1. SQLite FTS5 indexer for event/run search
2. `hanno search` CLI command
3. SearchIndexer implementations

---

## Verification

After each milestone:

- `uv run pytest --cov` — all tests pass, coverage reported
- `uv run ruff check .` — no lint errors
- `uv run mypy packages/hanno-core/src` — type checks pass

After Milestone A: programmatic usage works (create run, add steps, complete lifecycle)
After Milestone B: `hanno run create test && hanno run list` works
After Milestone C: MCP server responds to tool calls via test client

## Implementation Order

We will implement **Milestone 0 first**, then **Milestone A** (A.1 → A.2 → A.3 → A.4 → A.5 → A.6), then proceed to B/C/D based on priority.
