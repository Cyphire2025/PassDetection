"""One fixed, read-only administrative observation with no scope override."""

from typing import Any

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.admin_overview_reads import (
    AdminOverviewReadError,
    MCPAdminOverviewReadService,
)
from app.application.mcp.authorization import MCPPrincipal
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.presentation.mcp.invocation import MCPInputError, invoke_read


def register_admin_overview_read_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    annotations = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

    @server.tool(annotations=annotations, meta={"capability": "mcp:read"})
    async def get_admin_overview() -> dict[str, Any]:
        """Read seven canonical global administrative counts as a current Superadmin.

        These are separate live counts with retained-record website semantics,
        not an atomic snapshot, personal records or runtime/service health.
        This never changes settings, users, business records or sends messages.
        """
        async def read(session: AsyncSession, principal: MCPPrincipal) -> dict[str, Any]:
            try:
                return await MCPAdminOverviewReadService(session, settings).get_overview(principal)
            except AdminOverviewReadError as exc:
                messages = {
                    "admin_overview_busy": "Administrative overview is temporarily busy. Retry this same read shortly.",
                    "admin_overview_limit": "The complete administrative overview exceeds supported response or count bounds.",
                }
                raise MCPInputError(exc.code, messages[exc.code]) from exc
        return await invoke_read(app, settings, MCPToolPolicy("get_admin_overview", MCPCapability.READ, frozenset({"read"})), read)
