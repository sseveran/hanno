"""SearchIndexerHook — indexes ledger entities on event append."""

from __future__ import annotations

import logging

from hanno_core.interfaces.search import SearchBackend
from hanno_core.interfaces.storage import StorageBackend
from hanno_core.models import Event, EventKind, RunStatus

logger = logging.getLogger(__name__)

# Event kinds that trigger run re-indexing
_RUN_EVENTS = {
    EventKind.RUN_CREATED,
    EventKind.RUN_STARTED,
    EventKind.RUN_STATUS_CHANGED,
    EventKind.RUN_COMPLETED,
    EventKind.RUN_FAILED,
    EventKind.RUN_CANCELED,
}

# Event kinds that trigger step re-indexing
_STEP_EVENTS = {
    EventKind.STEP_CREATED,
    EventKind.STEP_STARTED,
    EventKind.STEP_COMPLETED,
    EventKind.STEP_FAILED,
    EventKind.STEP_SKIPPED,
}


class SearchIndexerHook:
    """Hook that indexes ledger entities into a SearchBackend.

    Listens for on_event_appended and indexes both the event itself
    and the parent entity (Run, StepRun, or Artifact) based on event kind.
    """

    def __init__(
        self,
        search: SearchBackend,
        storage: StorageBackend,
    ) -> None:
        self._search = search
        self._storage = storage

    async def on_event_appended(self, event: Event) -> None:
        # Always index the event itself
        try:
            await self._search.index_event(event)
        except Exception:
            logger.warning("Failed to index event %s", event.id, exc_info=True)

        # Index parent entity based on event kind
        try:
            if event.kind in _RUN_EVENTS:
                run = await self._storage.get_run(event.run_id)
                if run:
                    await self._search.index_run(run)

            elif event.kind in _STEP_EVENTS and event.step_run_id:
                step = await self._storage.get_step_run(event.step_run_id)
                if step:
                    await self._search.index_step_run(step)

            elif event.kind == EventKind.ARTIFACT_ATTACHED:
                artifact_id = event.payload.get("artifact_id")
                if artifact_id:
                    artifact = await self._storage.get_artifact(str(artifact_id))
                    if artifact:
                        await self._search.index_artifact(artifact)
        except Exception:
            logger.warning(
                "Failed to index parent entity for event %s (kind=%s)",
                event.id,
                event.kind,
                exc_info=True,
            )

    async def on_run_completed(self, run_id: str, final_status: RunStatus) -> None:
        # No-op — run is already re-indexed via the event-based path
        pass
