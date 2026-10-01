"""A single compact read for a linked broadcast's submitted phone differences."""
from typing import Annotated, Any
from uuid import UUID

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.phone_difference_reads import MCPPhoneDifferenceReadService
from app.application.mcp.read_access import current_read_access
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.presentation.mcp.invocation import MCPInputError, invoke_read
from app.presentation.mcp.observational_session import observational_session


def register_phone_difference_read_tools(server: MCPServer, app: FastAPI, settings: Settings):
    @server.tool(meta={"capability": "mcp:read"},
        annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False))
    async def list_submission_phone_differences(group_id: UUID, broadcast_id: UUID | None = None,
        agency_id: UUID | None = None, offset: Annotated[int, Field(ge=0, le=100000)] = 0,
        page_size: Annotated[int, Field(ge=1, le=100)] = 50,
        snapshot_revision: Annotated[str | None, Field(pattern=r"^[0-9a-f]{64}$")] = None) -> dict[str, Any]:
        """Compare submitted phone numbers against a linked WhatsApp broadcast in one compact read.

        Prefer this tool to retrieving hundreds of full matching records when the
        question concerns changed phone numbers. The canonical dashboard matcher
        runs once per call. Only high-confidence unambiguous submitted matches
        with two valid, different normalized numbers are returned, with both
        names/numbers, staff codes, match basis, record IDs and coverage counts.
        Missing/invalid phones and ambiguous/review matches are counted separately.
        Omit broadcast_id only for a group with exactly one linked broadcast.
        Follow next_offset using unchanged options and snapshot_revision; changed
        matching inputs require a fresh comparison. This is a data read, not an
        export: an agent may create a local workbook from the returned data.
        No customer record edits, file downloads or messages are performed.
        """
        async def read(session: AsyncSession, principal: MCPPrincipal):
            _, revision = await current_read_access(session, lock=True)
            try:
                async with observational_session(session):
                    result = await MCPPhoneDifferenceReadService(session, cursor_secret=settings.app_secret_key).read(
                        user_id=principal.user_id, group_id=group_id, broadcast_id=broadcast_id,
                        agency_id=agency_id, offset=offset, page_size=page_size, snapshot_revision=snapshot_revision)
                result["read_access_revision"] = revision
                return result
            except ValueError as exc:
                raise MCPInputError("invalid_phone_comparison", str(exc)) from exc
        return await invoke_read(app, settings,
            MCPToolPolicy("list_submission_phone_differences", MCPCapability.READ, frozenset({"read"})), read)
