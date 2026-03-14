"""WorkspaceRepo models — explicit repo membership inside a workspace."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field
from ulid import ULID


class WorkspaceRepo(BaseModel):
    """A repo resource attached to a workspace."""

    id: str = Field(default_factory=lambda: str(ULID()))

    workspace_id: str
    """Parent workspace."""

    vcs: str = "git"
    """Version control system identifier."""

    display_name: str = ""
    """Human-readable name, typically the repo name."""

    canonical_remote: str = ""
    """Normalized remote identifier used for repo-context matching."""

    local_path: str | None = None
    """Optional local checkout path."""

    default_branch: str | None = None
    """Optional default branch."""

    metadata: dict[str, object] = Field(default_factory=dict)
    """Arbitrary metadata."""

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TaskRepoLink(BaseModel):
    """Explicit repo membership for a task."""

    id: str = Field(default_factory=lambda: str(ULID()))

    task_id: str
    workspace_repo_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
