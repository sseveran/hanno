"""StateVersion model — append-only state snapshots."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field
from ulid import ULID

from .identity import ActorRef


class StateVersion(BaseModel):
    """A versioned snapshot of a run's working state,
    stored as an append-only series tied to the event stream.
    """

    id: str = Field(default_factory=lambda: str(ULID()))

    run_id: str

    sequence: int
    """Event sequence number this snapshot corresponds to."""

    prev_state_version_id: str | None = None
    """Previous snapshot in the chain."""

    state_ref: str
    """URI/ref to the state blob in ArtifactStore."""

    state_hash: str
    """Hash of the state blob for integrity verification."""

    actor: ActorRef

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
