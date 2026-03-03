"""MCP tools for approval operations."""

from __future__ import annotations

from hanno_core.engine.ledger import InvalidTransitionError, LedgerError
from hanno_core.models.identity import ActorRef
from mcp.server.fastmcp import FastMCP

from hanno_mcp.config import open_ledger

ACTOR = ActorRef(provider="mcp", identifier="agent")


def register(mcp: FastMCP) -> None:
    """Register approval tools on the MCP server."""

    @mcp.tool()
    async def hanno_request_approval(
        run_id: str,
        authority: str = "",
        resource: str = "",
        step_run_id: str | None = None,
    ) -> str:
        """Request an approval for a run (e.g. human sign-off before deploy).

        Args:
            run_id: The run ID (ULID).
            authority: Who should approve (e.g. 'team-lead', 'security').
            resource: What is being approved (e.g. 'production-deploy').
            step_run_id: Optional step run ID to associate with.
        """
        async with open_ledger() as ledger:
            try:
                approval = await ledger.request_approval(
                    run_id,
                    actor=ACTOR,
                    authority=authority,
                    resource=resource,
                    step_run_id=step_run_id,
                )
                return approval.model_dump_json()
            except LedgerError as e:
                return _error(str(e))

    @mcp.tool()
    async def hanno_grant_approval(approval_id: str) -> str:
        """Grant a pending approval.

        Args:
            approval_id: The approval ID (ULID).
        """
        async with open_ledger() as ledger:
            try:
                approval = await ledger.grant_approval(approval_id, actor=ACTOR)
                return approval.model_dump_json()
            except (LedgerError, InvalidTransitionError) as e:
                return _error(str(e))

    @mcp.tool()
    async def hanno_deny_approval(approval_id: str, reason: str = "") -> str:
        """Deny a pending approval.

        Args:
            approval_id: The approval ID (ULID).
            reason: Optional reason for denial.
        """
        async with open_ledger() as ledger:
            try:
                approval = await ledger.deny_approval(
                    approval_id, actor=ACTOR, reason=reason
                )
                return approval.model_dump_json()
            except (LedgerError, InvalidTransitionError) as e:
                return _error(str(e))

    @mcp.tool()
    async def hanno_list_approvals(
        run_id: str,
        pending_only: bool = False,
    ) -> str:
        """List approvals for a run.

        Args:
            run_id: The run ID (ULID).
            pending_only: If true, only return pending approvals.
        """
        from hanno_core.models import ApprovalStatus

        async with open_ledger() as ledger:
            status = ApprovalStatus.PENDING if pending_only else None
            approvals = await ledger.list_approvals(run_id, status=status)
            return "[" + ",".join(a.model_dump_json() for a in approvals) + "]"


def _error(message: str) -> str:
    import json

    return json.dumps({"error": message})
