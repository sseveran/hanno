"""Run model — one workflow instance."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field
from ulid import ULID

from .enums import RunStatus


def _ulid_str() -> str:
    return str(ULID())


def _now() -> datetime:
    return datetime.now(UTC)


class Run(BaseModel):
    """A Run is one workflow instance (e.g. PR authoring, incident RCA)."""

    id: str = Field(default_factory=_ulid_str)

    run_type: str
    """Workflow type identifier, e.g. 'pr_authoring', 'quant_research'."""

    status: RunStatus = RunStatus.PLANNED

    title: str = ""
    """Human-readable title for the run."""

    links: list[str] = []
    """External references: PR URLs, incident IDs, paper DOIs, etc."""

    labels: dict[str, str] = {}
    """Arbitrary key-value labels for filtering."""

    metadata: dict[str, object] = {}
    """Arbitrary metadata."""

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
