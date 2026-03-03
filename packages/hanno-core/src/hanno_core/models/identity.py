"""Pluggable actor identity model."""

from pydantic import BaseModel


class ActorRef(BaseModel, frozen=True):
    """Pluggable identity reference. The ledger does not solve identity —
    it stores references that an optional IdentityProvider can normalize later.
    """

    provider: str
    """Identity provider name, e.g. 'github', 'local', 'api-key'."""

    identifier: str
    """Subject identifier within the provider, e.g. 'steve', 'agent-xyz'."""

    display_name: str | None = None
    """Optional human-readable display name."""

    metadata: dict[str, str] = {}
    """Provider-specific metadata (e.g. email, avatar URL)."""
