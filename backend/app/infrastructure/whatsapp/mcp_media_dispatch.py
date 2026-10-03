"""Owned header and linked upload-group checks after the original grant barrier."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.credentials import MCPAuthError, credential_hash, utc
from app.application.mcp.permissions import require_tool_access
from app.core.config.settings import Settings
from app.infrastructure.database.mcp_communication_models import MCPWhatsAppPlanModel
from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.mcp_whatsapp_media_models import (
    MCPWhatsAppHeaderAccessModel,
    MCPWhatsAppHeaderMediaModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastGroupModel,
)


async def ready_plan_media(
    session: AsyncSession, plan: MCPWhatsAppPlanModel, grant: MCPGrantModel, settings: Settings
) -> bool:
    try:
        await require_tool_access(session, settings, grant.id, "upload_whatsapp_header", "mcp:upload", lock=False)
    except MCPAuthError:
        return False
    snapshot = plan.snapshot
    header = snapshot.get("header_media")
    if (
        not isinstance(header, dict)
        or "mcp:upload" not in grant.capabilities
        or "mcp:upload" not in settings.mcp.effective_capabilities
    ):
        return False
    if header.get("access_grant_id") != str(grant.id):
        return False
    linked = snapshot.get("linked_upload_group")
    if snapshot["worker_payload"]["message_type"] == "passport_link":
        if not isinstance(linked, dict):
            return False
        group = await session.scalar(
            select(ClientGroupModel)
            .where(
                ClientGroupModel.id == uuid.UUID(linked["client_group_id"]),
                ClientGroupModel.agency_id == plan.agency_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            group is None
            or group.status != "active"
            or group.deleted_at is not None
            or not group.token
        ):
            return False
        current_url = (
            settings.mcp.frontend_origin.rstrip("/") + "/upload/" + quote(group.token, safe="")
        )
        if (
            linked.get("url") != current_url
            or snapshot["worker_payload"].get("passport_link") != current_url
        ):
            return False
        link = await session.scalar(
            select(ClientGroupWhatsAppBroadcastLinkModel.id).where(
                ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
                ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id == plan.broadcast_id,
                ClientGroupWhatsAppBroadcastLinkModel.agency_id == plan.agency_id,
            )
        )
        if link is None:
            return False
    agency = await session.scalar(
        select(AgencyModel).where(AgencyModel.id == plan.agency_id).with_for_update(read=True)
    )
    broadcast = await session.scalar(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == plan.broadcast_id,
            WhatsAppBroadcastGroupModel.agency_id == plan.agency_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        agency is None
        or not agency.is_active
        or broadcast is None
        or broadcast.archived_at is not None
        or broadcast.recipient_opt_in_confirmed_at is None
    ):
        return False
    media = await session.scalar(
        select(MCPWhatsAppHeaderMediaModel)
        .join(
            MCPWhatsAppHeaderAccessModel,
            MCPWhatsAppHeaderAccessModel.media_id == MCPWhatsAppHeaderMediaModel.id,
        )
        .where(
            MCPWhatsAppHeaderMediaModel.id == uuid.UUID(header["media_artifact_id"]),
            MCPWhatsAppHeaderMediaModel.user_id == plan.user_id,
            MCPWhatsAppHeaderMediaModel.agency_id == plan.agency_id,
            MCPWhatsAppHeaderMediaModel.broadcast_id == plan.broadcast_id,
            MCPWhatsAppHeaderAccessModel.grant_id == grant.id,
            MCPWhatsAppHeaderAccessModel.handle_hash
            == credential_hash(header["media_handle"], settings.app_secret_key),
        )
        .with_for_update(of=MCPWhatsAppHeaderMediaModel)
        .execution_options(populate_existing=True)
    )
    return bool(
        media is not None
        and media.status == "ready"
        and utc(media.expires_at) > datetime.now(UTC)
        and media.original_sha256 == header.get("original_sha256")
        and media.normalized_sha256 == header.get("provider_content_sha256")
        and media.provider_media_id
        == header.get("provider_media_id")
        == snapshot["worker_payload"].get("header_image_id")
        and media.provider_phone_number_id
        == header.get("provider_phone_number_id")
        == settings.whatsapp_phone_number_id
    )
