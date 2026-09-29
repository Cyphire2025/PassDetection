"""Read-only dashboard tool using the same agency summary as the website."""

from typing import Any

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.dashboard_reads import MCPDashboardReadService
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.domain.value_objects.dashboard_summary import DashboardProjectionLimitError
from app.presentation.mcp.invocation import MCPInputError, invoke_read


def register_dashboard_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    @server.tool(
        meta={"capability": "mcp:read"},
        annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False,
                                    idempotent_hint=True, open_world_hint=False),
    )
    async def get_dashboard_summary() -> dict[str, Any]:
        """Read the current account's agency dashboard counts and five latest submissions.

        No agency parameter or global aggregate is available. No agency means zero
        counts. Counts preserve website status/lifecycle rules; recent submissions
        are a fixed preview rather than pageable history. Separate live queries do
        not provide an atomic snapshot. No business records or exports are created.
        """
        async def read(session: AsyncSession, principal: MCPPrincipal) -> dict[str, Any]:
            try:
                return await MCPDashboardReadService(
                    session, cursor_secret=settings.app_secret_key,
                ).get_summary(principal.user_id)
            except DashboardProjectionLimitError as exc:
                raise MCPInputError("dashboard_summary_limit", "The complete dashboard summary exceeds its safe response bounds.") from exc
        return await invoke_read(app, settings,
            MCPToolPolicy("get_dashboard_summary", MCPCapability.READ, frozenset({"read"})), read)
