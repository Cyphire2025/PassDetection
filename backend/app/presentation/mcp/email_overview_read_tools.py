"""Fixed-size email readiness and personal mailbox summary tools."""

from typing import Any

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.email_overview_reads import (
    EmailOverviewReadError,
    MCPEmailOverviewReadService,
)
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.presentation.mcp.invocation import MCPInputError, invoke_read


def register_email_overview_read_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    annotations = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

    async def dispatch(name: str, *, summary: bool) -> dict[str, Any]:
        async def read(session: AsyncSession, principal: MCPPrincipal) -> dict[str, Any]:
            service = MCPEmailOverviewReadService(session, settings)
            try:
                return await (service.get_summary(principal) if summary else service.get_status(principal))
            except EmailOverviewReadError as exc:
                messages = {
                    "email_overview_busy": "Email overview is temporarily busy. Retry this same read shortly.",
                    "email_overview_limit": "The complete email overview exceeds supported response or count bounds.",
                }
                raise MCPInputError(exc.code, messages[exc.code]) from exc
        return await invoke_read(app, settings, MCPToolPolicy(name, MCPCapability.READ, frozenset({"read"})), read)

    @server.tool(annotations=annotations, meta={"capability": "mcp:read"})
    async def get_email_integration_status() -> dict[str, Any]:
        """Read fixed configuration readiness flags, never credential values or provider health.

        This does not authorize, connect, sync, enable settings or send anything.
        """
        return await dispatch("get_email_integration_status", summary=False)

    @server.tool(annotations=annotations, meta={"capability": "mcp:read"})
    async def get_my_email_integration_summary() -> dict[str, Any]:
        """Read seven canonical counts for mailboxes personally owned by this account.

        Today means UTC midnight. Counts are separate live observations, not an
        atomic snapshot. No scope override, message content, credential or file
        locator. This never syncs, retrieves, reviews, retries, or sends email.
        """
        return await dispatch("get_my_email_integration_summary", summary=True)
