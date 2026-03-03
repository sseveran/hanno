"""Tests for the hook registry."""

from hanno_core.hooks.registry import InProcessHookRegistry
from hanno_core.models import Event, EventKind, RunStatus
from hanno_core.models.identity import ActorRef


class MockHook:
    def __init__(self):
        self.events: list[Event] = []
        self.completions: list[tuple[str, RunStatus]] = []

    async def on_event_appended(self, event: Event) -> None:
        self.events.append(event)

    async def on_run_completed(self, run_id: str, final_status: RunStatus) -> None:
        self.completions.append((run_id, final_status))


class TestInProcessHookRegistry:
    async def test_fire_event(self):
        registry = InProcessHookRegistry()
        hook = MockHook()
        registry.register(hook)

        event = Event(
            run_id="r1",
            sequence=1,
            kind=EventKind.RUN_CREATED,
            actor=ActorRef(provider="test", identifier="agent"),
        )
        await registry.fire_event_appended(event)

        assert len(hook.events) == 1
        assert hook.events[0].id == event.id

    async def test_fire_run_completed(self):
        registry = InProcessHookRegistry()
        hook = MockHook()
        registry.register(hook)

        await registry.fire_run_completed("r1", RunStatus.SUCCEEDED)

        assert len(hook.completions) == 1
        assert hook.completions[0] == ("r1", RunStatus.SUCCEEDED)

    async def test_multiple_hooks(self):
        registry = InProcessHookRegistry()
        h1 = MockHook()
        h2 = MockHook()
        registry.register(h1)
        registry.register(h2)

        event = Event(
            run_id="r1",
            sequence=1,
            kind=EventKind.NOTE,
            actor=ActorRef(provider="test", identifier="agent"),
        )
        await registry.fire_event_appended(event)

        assert len(h1.events) == 1
        assert len(h2.events) == 1

    async def test_no_hooks_no_error(self):
        registry = InProcessHookRegistry()
        event = Event(
            run_id="r1",
            sequence=1,
            kind=EventKind.NOTE,
            actor=ActorRef(provider="test", identifier="agent"),
        )
        await registry.fire_event_appended(event)
        await registry.fire_run_completed("r1", RunStatus.SUCCEEDED)
