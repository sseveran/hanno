"""Run model — one workflow instance."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field
from ulid import ULID

from .enums import RunStatus


def _ulid_str() -> str:
    return str(ULID())


def _now() -> datetime:
    return datetime.now(UTC)


class ExternalRef(BaseModel):
    """A structured reference to an external system (GitHub issue, Jira ticket, etc.)."""

    system: str
    """External system identifier, e.g. 'github', 'jira', 'zendesk'."""

    ref_type: str
    """Type of reference, e.g. 'issue', 'pr', 'case', 'ticket'."""

    ref_id: str
    """System-specific identifier, e.g. 'org/repo#123', 'PROJ-456'."""

    url: str | None = None
    """Optional full URL to the external resource."""


class Run(BaseModel):
    """A Run is one workflow instance (e.g. PR authoring, incident RCA)."""

    id: str = Field(default_factory=_ulid_str)

    run_type: str
    """Workflow type identifier, e.g. 'pr_authoring', 'quant_research'."""

    status: RunStatus = RunStatus.PLANNED

    title: str = ""
    """Human-readable title for the run."""

    external_refs: list[ExternalRef] = []
    """Structured external references: GitHub issues, support cases, etc."""

    labels: dict[str, str] = {}
    """Arbitrary key-value labels for filtering."""

    session_id: str | None = None
    """Optional session this run belongs to."""

    metadata: dict[str, object] = {}
    """Arbitrary metadata."""

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
