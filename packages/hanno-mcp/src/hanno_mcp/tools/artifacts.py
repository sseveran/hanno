"""MCP tools for artifact operations."""

from __future__ import annotations

import base64
import binascii

from hanno_core.engine.ledger import LedgerError
from hanno_core.models.identity import ActorRef
from mcp.server.fastmcp import FastMCP

from hanno_mcp.config import open_ledger

ACTOR = ActorRef(provider="mcp", identifier="agent")


def register(mcp: FastMCP) -> None:
    """Register artifact tools on the MCP server."""

    @mcp.tool()
    async def hanno_attach_artifact(
        run_id: str,
        data_base64: str,
        kind: str,
        name: str = "",
        content_type: str = "application/octet-stream",
        step_run_id: str | None = None,
    ) -> str:
        """Attach an artifact (file, log, etc.) to a run.

        Args:
            run_id: The run ID (ULID).
            data_base64: Base64-encoded artifact data.
            kind: Artifact kind (e.g. 'log', 'report', 'screenshot').
            name: Optional human-readable name.
            content_type: MIME type (default 'application/octet-stream').
            step_run_id: Optional step run ID to associate the artifact with.
        """
        async with open_ledger() as ledger:
            try:
                data = base64.b64decode(data_base64)
                artifact = await ledger.attach_artifact(
                    run_id,
                    data=data,
                    kind=kind,
                    actor=ACTOR,
                    name=name,
                    content_type=content_type,
                    step_run_id=step_run_id,
                )
                return artifact.model_dump_json()
            except (LedgerError, binascii.Error, ValueError) as e:
                return _error(str(e))

    @mcp.tool()
    async def hanno_list_artifacts(
        run_id: str,
        step_run_id: str | None = None,
    ) -> str:
        """List artifacts attached to a run, optionally filtered by step.

        Args:
            run_id: The run ID (ULID).
            step_run_id: Optional step run ID to filter by.
        """
        async with open_ledger() as ledger:
            artifacts = await ledger.list_artifacts(run_id, step_run_id=step_run_id)
            return "[" + ",".join(a.model_dump_json() for a in artifacts) + "]"


def _error(message: str) -> str:
    import json

    return json.dumps({"error": message})
