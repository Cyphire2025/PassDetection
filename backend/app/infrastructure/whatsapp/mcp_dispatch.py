"""MCP authority barrier, held in the worker transaction through provider I/O."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError
from app.core.config.settings import Settings
from app.infrastructure.database.mcp_communication_models import (
    MCPWhatsAppOutboxModel,
    MCPWhatsAppPlanModel,
)
from app.infrastructure.database.models import WhatsAppMessageLogModel
from app.infrastructure.whatsapp.mcp_media_dispatch import ready_plan_media

BLOCKED = "MCP_DISPATCH_BLOCKED: original authority or exact prepared intent is no longer available"


async def authorize_mcp_batch_dispatch(
    session: AsyncSession, *, log: WhatsAppMessageLogModel, settings: Settings
) -> str | None:
    """Ordinary web batches pass through; an orphaned MCP marker fails closed.

    Read-only lookups resolve authority. Locks always acquire control -> original
    grant -> identity -> plan BEFORE the existing worker group/recipient locks.
    The worker must not commit between this check and its provider request.
    """
    binding = (
        await session.execute(
            select(MCPWhatsAppOutboxModel.plan_id).where(
                MCPWhatsAppOutboxModel.batch_id == log.batch_id
            )
        )
    ).first()
    if binding is None:
        return None
    if binding.plan_id is None:
        return BLOCKED
    identity = (
        await session.execute(
            select(MCPWhatsAppPlanModel.original_grant_id, MCPWhatsAppPlanModel.user_id).where(
                MCPWhatsAppPlanModel.id == binding.plan_id
            )
        )
    ).first()
    if identity is None or identity.original_grant_id is None or identity.user_id is None:
        return BLOCKED
    try:
        grant = await MCPAuthorizationService(session, settings).require_grant(
            identity.original_grant_id, lock=True
        )
    except MCPAuthError:
        return BLOCKED
    if (
        grant.user_id != identity.user_id
        or "mcp:communicate" not in grant.capabilities
        or "mcp:communicate" not in settings.mcp.effective_capabilities
    ):
        return BLOCKED
    plan = await session.scalar(
        select(MCPWhatsAppPlanModel)
        .where(MCPWhatsAppPlanModel.id == binding.plan_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        plan is None
        or plan.status != "queued"
        or plan.batch_id != log.batch_id
        or plan.broadcast_id != log.broadcast_group_id
    ):
        return BLOCKED
    message_type = plan.snapshot["worker_payload"].get("message_type")
    if message_type not in {"welcome", "passport_link", "reminder", "group_invite"}:
        return BLOCKED
    if message_type != "reminder" and not await ready_plan_media(session, plan, grant, settings):
        return BLOCKED
    recipient = next(
        (
            item
            for item in plan.snapshot["recipients"]
            if item["recipient_id"] == str(log.recipient_id)
        ),
        None,
    )
    if (
        recipient is None
        or log.message_type != message_type
        or any(
            (
                recipient["phone_number"] != log.normalized_phone_number,
                recipient["template_name"] != log.template_name,
                recipient["language"] != log.template_language,
                recipient["rendered_message"] != log.rendered_message,
                recipient["header_parameters"] != log.header_parameter_values,
                recipient["body_parameters"] != log.template_parameter_values,
            )
        )
    ):
        return BLOCKED
    return None
