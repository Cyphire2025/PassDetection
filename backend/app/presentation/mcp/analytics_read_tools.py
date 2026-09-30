"""Read-only canonical passport analytics tool; no operations or file effects."""

from typing import Any

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.analytics_reads import AnalyticsReadError, MCPPassportAnalyticsReadService
from app.application.mcp.authorization import MCPPrincipal
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.presentation.mcp.invocation import MCPInputError, invoke_read

MESSAGES = {
    "analytics_invalid_query": "Provide an integer day count; it is clamped to the website's 1 to 365 day window.",
    "analytics_read_limit": "The complete analytics projection exceeds its safe limits. No partial result was returned.",
    "analytics_read_busy": "Analytics are busy. Retry this read later.",
}


def register_analytics_read_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    @server.tool(
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
        ),
        meta={"capability": "mcp:read"},
    )
    async def get_passport_analytics_summary(days: int = 30) -> dict[str, Any]:
        """Read canonical office passport analytics across all agencies as Superadmin.

        Days clamps to 1..365. Three live scalar queries are not an atomic snapshot.
        The lower-only creation window includes future rows; date groups use the
        database session timezone. Confidence values between0.899 and0.9 fall in
        no bucket, so bucket sums need not equal other totals. No files or changes.
        """

        async def read(session: AsyncSession, principal: MCPPrincipal) -> dict[str, Any]:
            try:
                return await MCPPassportAnalyticsReadService(session, settings).summary(
                    principal, days=days
                )
            except AnalyticsReadError as exc:
                raise MCPInputError(exc.code, MESSAGES[exc.code]) from exc

        return await invoke_read(
            app,
            settings,
            MCPToolPolicy(
                "get_passport_analytics_summary", MCPCapability.READ, frozenset({"read"})
            ),
            read,
        )
