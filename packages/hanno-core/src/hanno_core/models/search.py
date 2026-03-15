"""Search models — result types and enumerations for search queries."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class EntityType(StrEnum):
    """Types of entities that can appear in search results."""

    RUN = "run"
    EVENT = "event"
    STEP_RUN = "step_run"
    ARTIFACT = "artifact"


class SearchMode(StrEnum):
    """Search strategy to use."""

    KEYWORD = "keyword"
    VECTOR = "vector"
    HYBRID = "hybrid"


class SearchResult(BaseModel):
    """A single search result with score and context."""

    entity_type: EntityType
    entity_id: str
    run_id: str
    score: float = Field(ge=0.0, le=1.0)
    snippet: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)
