"""Edge model — relationships between StepRuns."""

from pydantic import BaseModel, Field
from ulid import ULID

from .enums import EdgeKind


class Edge(BaseModel):
    """An edge between two StepRuns, representing workflow structure."""

    id: str = Field(default_factory=lambda: str(ULID()))

    run_id: str
    """Parent run."""

    from_step_run_id: str
    to_step_run_id: str

    kind: EdgeKind
    """Relationship type."""

    metadata: dict[str, object] = {}
