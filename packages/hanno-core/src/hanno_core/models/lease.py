"""Lease model — advisory leases for multi-agent coordination."""

import secrets
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from ulid import ULID

from .identity import ActorRef


class Lease(BaseModel):
    """An advisory lease for coordinating access among multiple agents."""

    id: str = Field(default_factory=lambda: str(ULID()))

    run_id: str

    lease_token: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    """Opaque token the holder uses to renew/release."""

    owner: ActorRef

    purpose: str = ""
    """Human-readable description of what the lease is for."""

    acquired_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    """When the lease expires if not renewed."""
