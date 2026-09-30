"""One explicit-group schedule observation; no retention mutation tools."""

from typing import Any
from uuid import UUID

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.retention_reads import MCPPassportRetentionReadService, RetentionReadError
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.presentation.mcp.invocation import MCPInputError, invoke_read


def register_retention_read_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    @server.tool(
        annotations=ToolAnnotations(
            read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
        ),
        meta={"capability": "mcp:read"},
    )
    async def get_group_passport_retention(group_id: UUID) -> dict[str, Any]:
        """Inspect the stored passport-retention schedule for exactly one group.

        Uses current Superadmin website scope, including archived/deleted groups
        and other agencies. Returns only IDs, the nullable saved purge date and
        nullable applied days, plus observation metadata. A stored date or null
        value does not prove purge execution or remaining files. This never
        schedules, cancels, deletes, runs cleanup, accesses files or changes
        retention policy. No mutation permission is conferred by this read.
        """

        async def read(session: AsyncSession, principal: MCPPrincipal) -> dict[str, Any]:
            try:
                return await MCPPassportRetentionReadService(session, settings).get_schedule(
                    principal, group_id=group_id
                )
            except RetentionReadError as exc:
                messages = {
                    "retention_invalid_group": "Provide one valid explicit group UUID.",
                    "retention_schedule_unavailable": "The group schedule is unavailable under current access policy.",
                    "retention_read_busy": "The schedule is being updated. Retry this same read shortly.",
                    "retention_read_limit": "The complete stored schedule observation exceeds supported bounds.",
                }
                raise MCPInputError(exc.code, messages[exc.code]) from exc

        return await invoke_read(
            app,
            settings,
            MCPToolPolicy("get_group_passport_retention", MCPCapability.READ, frozenset({"read"})),
            read,
        )
