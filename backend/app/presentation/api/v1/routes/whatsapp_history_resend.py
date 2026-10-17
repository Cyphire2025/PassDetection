"""A selected historical resend has a stable identity across HTTP retries."""

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.whatsapp_delivery_status import WHATSAPP_ACCEPTED_STATUSES
from app.infrastructure.database.models import WhatsAppMessageLogModel
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppResendRequest,
    WhatsAppSendResponse,
    WhatsAppSendResult,
)


def historical_resend_batch(
    body: WhatsAppResendRequest, *, user_id: uuid.UUID, group_id: uuid.UUID, recipient_id: uuid.UUID
) -> uuid.UUID | None:
    if body.request_id is None:
        return None
    if (
        body.source_message_log_id is None
        or body.include_previous_recipients
        or any(
            value is not None
            for value in (
                body.message_content,
                body.passport_intro,
                body.passport_link,
                body.group_invite_link,
                body.header_image_id,
                body.recipient_ids,
                body.support_contact_ids,
            )
        )
    ):
        raise HTTPException(
            422, "A historical resend must use its original saved message without overrides."
        )
    return uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"whatsapp-history:{user_id}:{group_id}:{recipient_id}:{body.message_type}:{body.source_message_log_id}:{body.request_id}",
    )


async def replay_historical_resend(
    session: AsyncSession,
    *,
    batch_id: uuid.UUID | None,
    group_id: uuid.UUID,
    recipient_id: uuid.UUID,
) -> WhatsAppSendResponse | None:
    if batch_id is None:
        return None
    log = await session.scalar(
        select(WhatsAppMessageLogModel).where(
            WhatsAppMessageLogModel.batch_id == batch_id,
            WhatsAppMessageLogModel.broadcast_group_id == group_id,
            WhatsAppMessageLogModel.recipient_id == recipient_id,
        )
    )
    if log is None:
        return None
    active = log.status in {"queued", "processing"}
    success = log.status in WHATSAPP_ACCEPTED_STATUSES
    unknown = log.status in {"delivery_unknown", "stalled"}
    return WhatsAppSendResponse(
        batch_id=batch_id,
        queued=int(active),
        sent=int(success),
        failed=int(not active and not success and not unknown),
        delivery_unknown=int(unknown),
        results=[
            WhatsAppSendResult(
                recipient_id=recipient_id,
                phone_number=log.normalized_phone_number or "",
                status=log.status,
                provider_message_id=log.provider_message_id,
                error_message=log.error_message,
            )
        ],
    )
