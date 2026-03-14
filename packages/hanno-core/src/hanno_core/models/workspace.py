"""Workspace model — the durable container for cross-repo work."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field
from ulid import ULID

from .enums import WorkspaceStatus
from .run import ExternalRef


class Workspace(BaseModel):
    """A Workspace groups related tasks and runs across repos and agents."""

    id: str = Field(default_factory=lambda: str(ULID()))

    title: str = ""
    """Human-readable title for the workspace."""

    status: WorkspaceStatus = WorkspaceStatus.ACTIVE

    external_refs: list[ExternalRef] = Field(default_factory=list)
    """Structured external references tied to the overall workspace."""

    labels: dict[str, str] = Field(default_factory=dict)
    """Arbitrary key-value labels for filtering."""

    metadata: dict[str, object] = Field(default_factory=dict)
    """Arbitrary metadata."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
