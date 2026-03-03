"""StepRun model — one execution of a step within a run."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field
from ulid import ULID

from .enums import StepRunStatus


class StepRun(BaseModel):
    """A StepRun is one execution of a step (repeatable for loops)."""

    id: str = Field(default_factory=lambda: str(ULID()))

    run_id: str
    """Parent run."""

    step_name: str
    """Skill-defined step name."""

    status: StepRunStatus = StepRunStatus.QUEUED

    iteration: int = 0
    """Iteration number for loop support."""

    parent_step_run_id: str | None = None
    """For nested steps."""

    started_at: datetime | None = None
    ended_at: datetime | None = None

    summary: str = ""
    """Short summary of step outcome."""

    metadata: dict[str, object] = {}

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
