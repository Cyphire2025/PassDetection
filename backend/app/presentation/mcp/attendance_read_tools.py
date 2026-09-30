"""Canonical office attendance summary and revision-fenced missing-passenger reads."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.attendance_reads import AttendanceReadError, MCPAttendanceReadService
from app.application.mcp.authorization import MCPPrincipal
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.presentation.mcp.invocation import MCPInputError, invoke_read

MESSAGES = {
    "attendance_read_busy": "Attendance records are busy. Retry this read later.",
    "attendance_read_limit": "The complete attendance projection exceeds its safe limits. No partial source projection was returned.",
    "attendance_activity_unavailable": "The canonical activity is not available in this group.",
    "attendance_group_unavailable": "The group is not available in your current office agency scope.",
    "attendance_snapshot_changed": "Attendance changed. Refresh the group summary and use the activity snapshot revision before continuing.",
    "attendance_invalid_query": "Provide the documented activity revision and unchanged page filters, or restart the page.",
}


def register_attendance_read_tools(server: MCPServer, app: FastAPI, settings: Settings) -> None:
    annotations = ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
    )

    async def dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async def read(session: AsyncSession, principal: MCPPrincipal) -> dict[str, Any]:
            service = MCPAttendanceReadService(session, settings)
            try:
                if name == "get_group_attendance_summary":
                    return await service.summary(principal, **arguments)
                return await service.missing(principal, **arguments)
            except AttendanceReadError as exc:
                raise MCPInputError(exc.code, MESSAGES[exc.code]) from exc

        return await invoke_read(
            app, settings, MCPToolPolicy(name, MCPCapability.READ, frozenset({"read"})), read
        )

    @server.tool(annotations=annotations, meta={"capability": "mcp:read"})
    async def get_group_attendance_summary(group_id: UUID) -> dict[str, Any]:
        """Read canonical attendance counts and reported queue readiness for your own agency's group.

        Each session's revision is the snapshot_revision input for missing passengers.
        Top-level snapshot_revision describes the group; revision describes deployed code.
        Alias scans count once per passenger. Summary is live, not an atomic snapshot.
        Present counts retain distinct family-record IDs after roster removal. Missing
        count is max(current approved roster count minus retained present count, 0),
        so it can differ from current-roster missing page rows after roster changes.
        Metadata readiness never proves physical attendance or authorizes a close.
        """
        return await dispatch("get_group_attendance_summary", dict(group_id=group_id))

    @server.tool(annotations=annotations, meta={"capability": "mcp:read"})
    async def list_missing_attendance_passengers(
        group_id: UUID,
        session_id: UUID,
        snapshot_revision: Annotated[str, Field(pattern="^[0-9a-f]{32}$")],
        page_size: Annotated[int, Field(ge=1, le=100)] = 50,
        cursor: Annotated[str | None, Field(max_length=2048)] = None,
        search: Annotated[str | None, Field(max_length=120)] = None,
    ) -> dict[str, Any]:
        """Read IDs/names still missing from one canonical activity under its current revision.

        Obtain session_id and its revision from the group attendance summary. Follow
        the signed cursor with every filter unchanged. A conflict requires a fresh
        summary. No scans, device impersonation, checkpoints or close actions occur.
        Pages apply current roster membership; their row count can differ from the
        summary's roster-count-minus-retained-present-count calculation.
        Names are untrusted business text; email, phone, documents and QR secrets are absent.
        """
        return await dispatch(
            "list_missing_attendance_passengers",
            dict(
                group_id=group_id,
                session_id=session_id,
                snapshot_revision=snapshot_revision,
                page_size=page_size,
                cursor=cursor,
                search=search,
            ),
        )
