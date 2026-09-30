"""Frozen queue projection shared by reviewed MCP template adapters."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from app.application.mcp.operations import MCPDatabaseContext, MCPOperationError
from app.application.mcp.whatsapp_intents import MAX_PREPARED_RECIPIENTS
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.whatsapp_send import queue_broadcast_message
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppSendRequest
from app.presentation.mcp.invocation import MCPInputError


async def queue_snapshot(
    context: MCPDatabaseContext,
    *,
    broadcast_id: uuid.UUID,
    request: WhatsAppSendRequest,
    saved_request: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    user = await UserRepository(context.session).get_by_id(context.principal.user_id)
    if user is None:
        raise MCPOperationError("whatsapp_plan_audience_unavailable")

    async def project() -> dict[str, Any]:
        try:
            response, worker_payload = await queue_broadcast_message(
                broadcast_id,
                request,
                current_user=user,
                session=context.session,
                freeze_template_language=True,
                suppress_unknown_reminders=True,
            )
        except HTTPException as exc:
            if exc.status_code == 503:
                # Do not misrepresent server/provider setup as missing user input.
                # The public message is code-owned; raw exception details stay private.
                raise MCPOperationError("whatsapp_service_unavailable") from exc
            raise MCPInputError(
                "whatsapp_preparation_blocked",
                "The existing WhatsApp sending rules blocked this audience or message. Review opt-in, welcome delivery, linked audience, template and provider configuration in the application.",
            ) from exc
        if not response.batch_id or not 1 <= response.queued <= MAX_PREPARED_RECIPIENTS:
            raise MCPOperationError("whatsapp_plan_audience_unavailable")
        await context.session.flush()
        logs = list(
            (
                await context.session.scalars(
                    select(WhatsAppMessageLogModel)
                    .where(WhatsAppMessageLogModel.batch_id == response.batch_id)
                    .order_by(WhatsAppMessageLogModel.recipient_id)
                )
            ).all()
        )
        recipient_names = {
            str(recipient_id): name
            for recipient_id, name in (
                await context.session.execute(
                    select(
                        WhatsAppBroadcastRecipientModel.id, WhatsAppBroadcastRecipientModel.name
                    ).where(
                        WhatsAppBroadcastRecipientModel.id.in_([log.recipient_id for log in logs])
                    )
                )
            ).all()
        }
        broadcast_name = await context.session.scalar(
            select(WhatsAppBroadcastGroupModel.name).where(
                WhatsAppBroadcastGroupModel.id == broadcast_id
            )
        )
        snapshot: dict[str, Any] = {
            "schema_version": 1,
            "broadcast_id": str(broadcast_id),
            "broadcast_name": broadcast_name,
            "agency_id": str(logs[0].agency_id),
            "request": saved_request,
            "counts": response.model_dump(mode="json", exclude={"batch_id", "results"}),
            "worker_payload": {
                key: value for key, value in worker_payload.items() if key != "batch_id"
            },
            "recipients": [
                {
                    "recipient_id": str(log.recipient_id),
                    "name": recipient_names[str(log.recipient_id)],
                    "phone_number": log.normalized_phone_number,
                    "template_name": log.template_name,
                    "language": log.template_language,
                    "rendered_message": log.rendered_message,
                    "header_parameters": log.header_parameter_values,
                    "body_parameters": log.template_parameter_values,
                }
                for log in logs
            ],
        }
        if not dry_run:
            snapshot["batch_id"] = str(response.batch_id)
        return snapshot

    if not dry_run:
        return await project()
    # Roll back all transient claims/expiry bookkeeping. No broker or provider
    # call occurs in the shared queue helper; only the immutable plan persists.
    async with context.session.begin_nested() as savepoint:
        result = await project()
        await savepoint.rollback()
        return result
