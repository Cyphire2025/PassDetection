"""Bounded discovery of every retained document, QR, welcome and broadcast attempt."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import FastAPI
from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPPrincipal
from app.application.mcp.delivery_reads import MCPDeliveryReadService
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.presentation.mcp.invocation import MCPInputError, invoke_read


def register_delivery_read_tools(server: MCPServer, app: FastAPI, settings: Settings):
    @server.tool(meta={"capability": "mcp:read"},
        annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False))
    async def list_delivery_records(kind: Literal["document", "qr", "broadcast", "welcome"],
        agency_id: UUID | None = None, group_id: UUID | None = None, broadcast_id: UUID | None = None,
        batch_id: UUID | None = None, passenger_id: UUID | None = None, recipient_id: UUID | None = None,
        status: Annotated[str | None, Field(min_length=1, max_length=50)] = None,
        message_type: Annotated[str | None, Field(min_length=1, max_length=50)] = None,
        include_contact_details: bool = False, include_deleted: bool = False, include_archived: bool = False,
        page_size: Annotated[int, Field(ge=1, le=100)] = 50,
        cursor: Annotated[str | None, Field(max_length=2048)] = None) -> dict[str, Any]:
        """Read every stored document/QR/welcome/broadcast delivery attempt and discover batch IDs.

        Follow next_cursor with unchanged options. group_id means client group;
        broadcast_id means WhatsApp broadcast. Broadcast attempts use broadcast_id,
        recipient_id and optional message_type; passenger/group filters apply to
        document/QR attempts. Older/deleted/archived data is explicit. Counts are
        attempts, not unique passengers, and statuses never authorize a resend.
        Use each detail_reference with read_dashboard_view for full saved fields.
        """
        async def read(session: AsyncSession, principal: MCPPrincipal):
            try:
                return await MCPDeliveryReadService(session, cursor_secret=settings.app_secret_key).list_records(
                    user_id=principal.user_id, kind=kind, agency_id=agency_id, group_id=group_id,
                    broadcast_id=broadcast_id, batch_id=batch_id, passenger_id=passenger_id,
                    recipient_id=recipient_id, status=status, message_type=message_type,
                    include_contact_details=include_contact_details, include_deleted=include_deleted,
                    include_archived=include_archived, page_size=page_size, cursor=cursor)
            except ValueError as exc:
                raise MCPInputError("invalid_delivery_read", str(exc)) from exc
        return await invoke_read(app, settings, MCPToolPolicy("list_delivery_records", MCPCapability.READ, frozenset({"read"})), read)
