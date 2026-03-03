"""Hook and HookRegistry protocols — event observation."""

from __future__ import annotations

from typing import Protocol

from hanno_core.models import Event, RunStatus


class Hook(Protocol):
    """Observer that reacts to ledger events and lifecycle transitions."""

    async def on_event_appended(self, event: Event) -> None: ...

    async def on_run_completed(
        self, run_id: str, final_status: RunStatus
    ) -> None: ...


class HookRegistry(Protocol):
    """Registry for hooks that observe ledger events."""

    def register(self, hook: Hook) -> None: ...

    async def fire_event_appended(self, event: Event) -> None: ...

    async def fire_run_completed(
        self, run_id: str, final_status: RunStatus
    ) -> None: ...
