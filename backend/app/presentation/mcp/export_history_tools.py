"""Metadata-only completed passport export history under current read authority."""

import uuid
from typing import Annotated, Any, Literal

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.export_history_reads import (
    ExportHistoryReadError,
    MCPExportHistoryReadService,
)
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.presentation.mcp.invocation import MCPInputError, invoke_read

ERRORS = {
    "history_limit": "Export history exceeds the configured source or response limit. Use a smaller page where possible.",
    "history_busy": "Export history is busy. Retry the same request later.",
    "history_integrity": "This export history entry failed its integrity check.",
    "history_unavailable": "Export history was not found in the requested authorized scope.",
    "history_invalid_request": "Invalid history selection, page or cursor. Restart the query with the documented filters.",
}
ANNOTATIONS = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


def register_export_history_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    async def invoke(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async def read(session: AsyncSession, principal: MCPPrincipal) -> dict[str, Any]:
            service = MCPExportHistoryReadService(session, settings)
            try:
                if name == "list_group_export_history":
                    return await service.list_history(principal, **arguments)
                return await service.get_history(principal, **arguments)
            except ExportHistoryReadError as exc:
                raise MCPInputError(exc.code, ERRORS[exc.code]) from exc
        return await invoke_read(app, settings, MCPToolPolicy(name, MCPCapability.READ, frozenset({"read"})), read)

    @server.tool(meta={"capability": "mcp:read"}, annotations=ANNOTATIONS)
    async def list_group_export_history(
        agency_id: uuid.UUID, group_id: uuid.UUID, kind: Literal["passport_excel", "passport_images"],
        page_size: Annotated[int, Field(ge=1, le=100)] = 25,
        cursor: Annotated[str | None, Field(max_length=2048)] = None,
        include_personal_details: bool = False, include_deleted: bool = False,
    ) -> dict[str, Any]:
        """List completed v1 website export checkpoints for an explicit agency/group.

        New-submission counts compare the live operational roster with each cumulative
        checkpoint, not the exported subset. Personal opt-in reveals the export actor's
        email. Retained deleted groups require include_deleted. The signed cursor binds
        this actor and all filters. No filenames, files, handles or recovery are exposed.
        """
        return await invoke("list_group_export_history", dict(agency_id=agency_id, group_id=group_id,
            kind=kind, page_size=page_size, cursor=cursor, include_personal_details=include_personal_details,
            include_deleted=include_deleted))

    @server.tool(meta={"capability": "mcp:read"}, annotations=ANNOTATIONS)
    async def get_group_export_history(
        agency_id: uuid.UUID, group_id: uuid.UUID, history_id: uuid.UUID,
        page: Annotated[int, Field(ge=1, le=5001)] = 1,
        page_size: Annotated[int, Field(ge=1, le=100)] = 50,
        include_personal_details: bool = False, include_deleted: bool = False,
    ) -> dict[str, Any]:
        """Read one completed v1 checkpoint's frozen passport IDs in exported order.

        Optional personal details are the retained name, phone, email and passport number,
        never current replacements. record_available means a same-scope source row exists;
        it does not attest file availability. Pending contact counts are separate from
        exported passports. This does not download, recover or mark an export complete.
        """
        return await invoke("get_group_export_history", dict(agency_id=agency_id, group_id=group_id,
            history_id=history_id, page=page, page_size=page_size,
            include_personal_details=include_personal_details, include_deleted=include_deleted))
