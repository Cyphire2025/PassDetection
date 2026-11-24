"""Scope an exact recipient selection and replay its durable request receipt."""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    AuditLogModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_support import refresh_batch_response
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBulkResendRequest,
    WhatsAppBulkResendResponse,
)

AUDIT_ACTION = "whatsapp_selected_messages_resend_requested"


async def replay_bulk_resend_request(
    session: AsyncSession,
    group: WhatsAppBroadcastGroupModel,
    body: WhatsAppBulkResendRequest,
    request_scope: uuid.UUID,
    fingerprint: str,
) -> WhatsAppBulkResendResponse | None:
    previous = (
        await session.execute(
            select(AuditLogModel).where(
                AuditLogModel.agency_id == group.agency_id,
                AuditLogModel.action == AUDIT_ACTION,
                AuditLogModel.entity_type == "whatsapp_bulk_resend_request",
                AuditLogModel.entity_id == str(request_scope),
            )
        )
    ).scalar_one_or_none()
    if previous is not None:
        receipt = previous.metadata_json or {}
        if receipt.get("selection_fingerprint") != fingerprint:
            raise HTTPException(
                status_code=409,
                detail="This resend request ID was already used for a different selection or message",
            )
        response = WhatsAppBulkResendResponse.model_validate(receipt["response"])
        # Receipt metadata deliberately stores no phone numbers or private message content.
        recipients = list(
            (
                await session.execute(
                    select(WhatsAppBroadcastRecipientModel).where(
                        WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
                        WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
                        WhatsAppBroadcastRecipientModel.id.in_(body.recipient_ids),
                    )
                )
            )
            .scalars()
            .all()
        )
        phones = {recipient.id: recipient.normalized_phone_number for recipient in recipients}
        response.results = [
            item.model_copy(update={"phone_number": phones.get(item.recipient_id, "")})
            for item in response.results
        ]
        response = await refresh_batch_response(session, response, replayed=True)
        await session.commit()
        return response
    return None


async def select_bulk_resend_recipients(
    session: AsyncSession,
    group: WhatsAppBroadcastGroupModel,
    body: WhatsAppBulkResendRequest,
) -> list[WhatsAppBroadcastRecipientModel]:
    recipients = list(
        (
            await session.execute(
                select(WhatsAppBroadcastRecipientModel)
                .where(
                    WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
                    WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
                    WhatsAppBroadcastRecipientModel.id.in_(body.recipient_ids),
                    WhatsAppBroadcastRecipientModel.removed_at.is_(None),
                )
                .order_by(WhatsAppBroadcastRecipientModel.id)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    if {recipient.id for recipient in recipients} != set(body.recipient_ids):
        # Validate the entire selection before creating any claim or revealing other lists.
        raise HTTPException(
            status_code=404,
            detail="One or more selected recipients are unavailable in this WhatsApp broadcast",
        )
    return recipients
