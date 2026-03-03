"""Event model — the atomic unit of the event-sourced system."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field
from ulid import ULID

from .enums import EventKind
from .identity import ActorRef


class Event(BaseModel):
    """An immutable event in the append-only event stream.
    Events are ordered by (run_id, sequence) and form the system of record.
    """

    id: str = Field(default_factory=lambda: str(ULID()))

    run_id: str
    """Parent run."""

    sequence: int
    """Monotonically increasing sequence number within the run."""

    kind: EventKind
    """Event type."""

    actor: ActorRef
    """Who caused this event."""

    payload: dict[str, object] = {}
    """Kind-specific data."""

    step_run_id: str | None = None
    """Optional association with a specific step."""

    parent_event_id: str | None = None
    """Optional causal parent event."""

    # OpenTelemetry correlation (optional)
    trace_id: str | None = None
    span_id: str | None = None

    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
