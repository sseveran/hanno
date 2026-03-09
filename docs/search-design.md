# Hanno Search Design

## Overview

Search over all data captured by the workflow ledger: runs, events, steps, artifacts, and their content. The design follows Hanno's existing pattern of pluggable backends via `typing.Protocol`, making search optional and backend-agnostic.

Inspired by [qmd](https://github.com/tobi/qmd) — a local-first hybrid search engine that combines FTS5 (BM25), sqlite-vec (vector search), and LLM re-ranking with Reciprocal Rank Fusion.

## What Gets Indexed

| Source | Keyword (FTS) | Vector (Embeddings) |
|--------|:---:|:---:|
| `Run.title` | yes | yes |
| `Run.labels` / `Run.metadata` | yes | no |
| `StepRun.step_name` + `summary` | yes | yes |
| `Event.payload` (JSON serialized) | yes | yes |
| `Artifact.name` + `kind` | yes | yes |
| Artifact **content** (text blobs) | yes | yes |
| `ExternalRef` fields | yes | no |

## Search Modes

Following qmd's three-mode pattern:

1. **`keyword`** — BM25 full-text search only (fastest, good for specific terms)
2. **`vector`** — Semantic similarity via embeddings (good for conceptual queries)
3. **`hybrid`** (default) — Both keyword + vector, merged via Reciprocal Rank Fusion (RRF)

## SearchBackend Protocol

```python
class SearchBackend(Protocol):
    async def initialize(self) -> None: ...
    async def close(self) -> None: ...

    # Indexing — called by RunLedger on writes
    async def index_run(self, run: Run) -> None: ...
    async def index_event(self, event: Event) -> None: ...
    async def index_step_run(self, step: StepRun) -> None: ...
    async def index_artifact(self, artifact: Artifact, content: bytes | None = None) -> None: ...

    # Search
    async def search(
        self,
        query: str,
        *,
        mode: SearchMode = SearchMode.HYBRID,
        entity_types: set[EntityType] | None = None,
        run_id: str | None = None,
        run_type: str | None = None,
        status: RunStatus | None = None,
        after: datetime | None = None,
        before: datetime | None = None,
        labels: dict[str, str] | None = None,
        limit: int = 20,
    ) -> list[SearchResult]: ...

    # "More like this" — find similar entities by embedding
    async def find_similar(
        self,
        entity_type: EntityType,
        entity_id: str,
        *,
        limit: int = 10,
    ) -> list[SearchResult]: ...
```

## SearchResult Model

```python
class SearchResult(BaseModel):
    entity_type: EntityType  # run | event | step_run | artifact
    entity_id: str
    run_id: str
    score: float             # normalized 0-1
    snippet: str             # highlighted match context
    metadata: dict[str, object] = {}
```

## Backend Implementations

### Tier: Built-in (no extra services)

| Backend | Technology | Hybrid | Notes |
|---------|-----------|:------:|-------|
| SQLite FTS5 + sqlite-vec | SQLite extensions | yes | Zero deps, ships with hanno-core |
| Postgres tsvector + pgvector | PostgreSQL extensions | yes | For hanno-postgres users |

### Tier: Embedded (pip install, no server)

| Backend | Technology | Hybrid | Notes |
|---------|-----------|:------:|-------|
| LanceDB | Rust-based, Tantivy FTS | yes | Best balance of simplicity + power |

### Tier: Server-based (external service)

| Backend | Technology | Hybrid | Notes |
|---------|-----------|:------:|-------|
| Qdrant | Rust vector DB | yes | Advanced filtering, RRF/DBSF fusion |
| OpenSearch | Java/Lucene | yes | Enterprise scale, BM25 + HNSW |
| Meilisearch | Rust search engine | yes | Great DX, new embedder system |

## Package Structure

```
packages/hanno-core/
  src/hanno_core/
    interfaces/search.py       — SearchBackend protocol
    models/search.py           — SearchResult, SearchMode, EntityType

packages/hanno-search/            — NEW package
  src/hanno_search/
    backends/
      sqlite_fts.py            — FTS5 + sqlite-vec
      lancedb.py               — LanceDB embedded
      qdrant.py                — Qdrant client
      opensearch.py            — OpenSearch client
      meilisearch.py           — Meilisearch client
    embeddings/
      protocol.py              — EmbeddingProvider protocol
      local.py                 — sentence-transformers / ONNX
      openai.py                — OpenAI embeddings API
      ollama.py                — local Ollama
    chunking.py                — smart content chunking
    fusion.py                  — RRF + score normalization

packages/hanno-postgres/
  src/hanno_postgres/
    search.py                  — pgvector-based SearchBackend

packages/hanno-cli/              — `hanno search` command
packages/hanno-mcp/              — `search_ledger` MCP tool
```

## Integration with RunLedger

Search is optional. `RunLedger` accepts an optional `SearchBackend` and indexes on write:

```python
class RunLedger:
    def __init__(self, storage: StorageBackend, search: SearchBackend | None = None):
        self._search = search

    async def append_event(self, ...):
        event = await self._storage.append_event(event)
        if self._search:
            await self._search.index_event(event)
        return event
```

This keeps the event-sourced architecture clean — search is a projection of the event stream, not part of the core write path.

## Embedding Strategy

### Provider Protocol

```python
class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...
    @property
    def dimensions(self) -> int: ...
```

### Implementations

- **Local (default)**: `all-MiniLM-L6-v2` via sentence-transformers or ONNX — no API keys
- **OpenAI**: `text-embedding-3-small` via API
- **Ollama**: any embedding model running locally

### Configuration

```bash
HANNO_SEARCH_BACKEND=sqlite      # sqlite | lancedb | qdrant | opensearch | meilisearch
HANNO_EMBEDDING_PROVIDER=local   # local | openai | ollama
HANNO_EMBEDDING_MODEL=all-MiniLM-L6-v2
```

### Lazy Loading (from qmd)

- Embedding model only loaded on first search/index call
- Auto-disposed after idle timeout (configurable, default 5 min)
- Model files cached locally (~100-500MB depending on model)

## Fusion & Ranking (from qmd)

### Reciprocal Rank Fusion (RRF)

When combining keyword and vector results:

```
RRF_score(d) = Σ 1 / (k + rank_i(d))
```

Where `k` is a constant (typically 60) and `rank_i(d)` is the rank of document `d` in result list `i`.

### Score Normalization

Each backend normalizes scores to 0-1:
- **BM25**: `abs(score) / reference_max`
- **Vector**: `1 / (1 + distance)` for cosine distance
- **Combined**: RRF produces a fused score, then normalized

## Smart Chunking

For long content (event payloads, artifact text), chunk on semantic boundaries:

- Respect markdown structure (headers, paragraphs, code blocks)
- Target ~800-900 tokens per chunk with 15% overlap
- Use a scoring algorithm to find natural break points (not hard token cuts)
- Store chunk-to-entity mapping for result attribution

## CLI Surface

```bash
hanno search "auth failure"                          # hybrid search (default)
hanno search "auth failure" --mode keyword            # FTS only
hanno search "auth failure" --mode vector             # semantic only
hanno search "auth failure" --type run --status failed
hanno search "auth failure" --after 2026-01-01 --before 2026-03-01
hanno search --similar run:01ABC123                   # "more like this"
hanno search "deploy" --run-type ci_pipeline --json   # machine-readable
```

## MCP Tool

```python
@server.tool()
async def search_ledger(
    query: str,
    mode: str = "hybrid",
    entity_types: list[str] | None = None,
    run_id: str | None = None,
    run_type: str | None = None,
    status: str | None = None,
    after: str | None = None,
    before: str | None = None,
    limit: int = 20,
) -> list[dict]: ...
```

## Build Order

1. **Protocol + models** in hanno-core (`SearchBackend`, `SearchResult`, `SearchMode`, `EntityType`)
2. **SQLite FTS5 backend** — keyword-only, immediate value, no embedding deps
3. **Embedding pipeline** + sqlite-vec — adds vector search to SQLite backend
4. **LanceDB backend** — best embedded hybrid alternative
5. **CLI `hanno search` + MCP `search_ledger`** integration
6. **Postgres backend** with pgvector
7. **Server backends** (Qdrant, OpenSearch, Meilisearch) as needed

Steps 1-2 deliver usable search fast. Step 3 adds semantic search. Steps 4+ are scale/preference options.

## Research References

- [qmd (tobi/qmd)](https://github.com/tobi/qmd) — local hybrid search engine combining FTS5, sqlite-vec, and LLM re-ranking
- [LanceDB](https://lancedb.github.io/lancedb/) — embedded vector DB with Tantivy-powered FTS
- [Qdrant hybrid search](https://qdrant.tech/articles/hybrid-search/) — RRF and DBSF fusion strategies
- [pgvector](https://github.com/pgvector/pgvector) — vector similarity for PostgreSQL
- [sqlite-vec](https://github.com/asg017/sqlite-vec) — vector search as SQLite extension
- [Meilisearch AI search](https://www.meilisearch.com/docs/learn/ai_powered_search/getting_started_with_ai_search) — hybrid semantic + keyword
- [Reciprocal Rank Fusion](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf) — original RRF paper
