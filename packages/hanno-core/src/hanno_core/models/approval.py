"""Approval model — approval requests and resolutions."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field
from ulid import ULID

from .enums import ApprovalStatus
from .identity import ActorRef


class Approval(BaseModel):
    """An approval request and its resolution state."""

    id: str = Field(default_factory=lambda: str(ULID()))

    run_id: str

    step_run_id: str | None = None
    """Optional association with a specific step."""

    status: ApprovalStatus = ApprovalStatus.PENDING

    authority: str = ""
    """Who/what has authority to approve (e.g. 'github', 'human:steve')."""

    resource: str = ""
    """What resource is being approved (e.g. PR URL)."""

    criteria: dict[str, object] = {}
    """Structured criteria for approval (e.g. {'approvals': 2})."""

    requested_by: ActorRef
    resolved_by: ActorRef | None = None

    reason: str = ""
    """Reason for grant/denial."""

    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    resolved_at: datetime | None = None
