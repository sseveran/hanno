"""In-process hook registry implementation."""

from __future__ import annotations

from hanno_core.models import Event, RunStatus


class InProcessHookRegistry:
    """Simple hook registry that fires async callbacks on ledger events."""

    def __init__(self) -> None:
        self._hooks: list[object] = []

    def register(self, hook: object) -> None:
        self._hooks.append(hook)

    async def fire_event_appended(self, event: Event) -> None:
        for hook in self._hooks:
            if hasattr(hook, "on_event_appended"):
                await hook.on_event_appended(event)

    async def fire_run_completed(self, run_id: str, final_status: RunStatus) -> None:
        for hook in self._hooks:
            if hasattr(hook, "on_run_completed"):
                await hook.on_run_completed(run_id, final_status)
