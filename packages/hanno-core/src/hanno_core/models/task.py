"""Task model — a task-like grouping of runs inside a workspace."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field
from ulid import ULID

from .enums import TaskStatus
from .run import ExternalRef


class Task(BaseModel):
    """A Task groups related runs for a specific objective within a workspace."""

    id: str = Field(default_factory=lambda: str(ULID()))

    workspace_id: str
    """Parent workspace."""

    title: str = ""
    """Human-readable title for the task."""

    status: TaskStatus = TaskStatus.ACTIVE

    external_refs: list[ExternalRef] = Field(default_factory=list)
    """Structured external references: PRs, tickets, docs, etc."""

    labels: dict[str, str] = Field(default_factory=dict)
    """Arbitrary key-value labels for filtering."""

    metadata: dict[str, object] = Field(default_factory=dict)
    """Arbitrary metadata."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
