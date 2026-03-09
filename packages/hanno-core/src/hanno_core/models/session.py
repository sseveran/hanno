"""Session model — a container that groups related runs."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field
from ulid import ULID

from .enums import SessionStatus
from .run import ExternalRef


class Session(BaseModel):
    """A Session groups related Runs (e.g., all work on a single PR)."""

    id: str = Field(default_factory=lambda: str(ULID()))

    title: str = ""
    """Human-readable title for the session."""

    status: SessionStatus = SessionStatus.ACTIVE

    external_refs: list[ExternalRef] = []
    """Structured external references: GitHub PRs, issues, etc."""

    labels: dict[str, str] = {}
    """Arbitrary key-value labels for filtering."""

    metadata: dict[str, object] = {}
    """Arbitrary metadata."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
