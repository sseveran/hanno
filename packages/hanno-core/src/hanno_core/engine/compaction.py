"""Compaction — transcript bundle and AAR generation."""

from __future__ import annotations

import json
from collections.abc import Sequence

from hanno_core.models import Event

from .projections import project_run_status, project_step_statuses, project_timeline


def generate_transcript_bundle(events: Sequence[Event]) -> bytes:
    """Generate a JSONL transcript bundle from events.

    Each line is a JSON record with type, sequence range, and content.
    """
    lines: list[str] = []
    for event in events:
        record = {
            "type": "event",
            "id": event.id,
            "run_id": event.run_id,
            "sequence": event.sequence,
            "kind": event.kind.value,
            "actor": event.actor.model_dump(),
            "payload": event.payload,
            "step_run_id": event.step_run_id,
            "timestamp": event.timestamp.isoformat(),
        }
        lines.append(json.dumps(record, default=str))
    return "\n".join(lines).encode()


def generate_aar(events: Sequence[Event], *, run_type: str = "") -> dict[str, object]:
    """Generate a structured After-Action Report from events.

    Returns a dict suitable for JSON serialization.
    """
    final_status = project_run_status(events)
    step_statuses = project_step_statuses(events)
    timeline = project_timeline(events)

    first_event = events[0] if events else None
    last_event = events[-1] if events else None

    return {
        "run_type": run_type,
        "final_status": final_status.value,
        "event_count": len(events),
        "started_at": first_event.timestamp.isoformat() if first_event else None,
        "ended_at": last_event.timestamp.isoformat() if last_event else None,
        "step_summary": {
            sid: status.value for sid, status in step_statuses.items()
        },
        "timeline": timeline,
    }
