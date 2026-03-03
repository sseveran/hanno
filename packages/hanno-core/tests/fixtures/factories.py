"""Test data factories for hanno-core tests."""

from hanno_core.models.identity import ActorRef


def make_actor(
    provider: str = "test",
    identifier: str = "test-agent",
    display_name: str | None = None,
) -> ActorRef:
    return ActorRef(
        provider=provider,
        identifier=identifier,
        display_name=display_name,
    )
