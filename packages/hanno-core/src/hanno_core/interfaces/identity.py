"""IdentityProvider protocol — optional identity normalization."""

from __future__ import annotations

from typing import Protocol

from hanno_core.models import ActorRef


class IdentityProvider(Protocol):
    """Optional provider that normalizes ActorRef to a canonical identity."""

    async def normalize(self, actor_ref: ActorRef) -> str:
        """Return a canonical identifier string for the given actor ref."""
        ...
