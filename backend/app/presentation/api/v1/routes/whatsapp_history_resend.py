"""A selected historical resend has a stable identity across HTTP retries."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

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

if TYPE_CHECKING:
    from app.presentation.api.v1.routes.whatsapp_composer_support import _WhatsAppComposerSnapshot


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


async def saved_resend_source(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    recipient_id: uuid.UUID,
    message_type: str,
    is_retry: bool,
    source_message_log_id: uuid.UUID | None,
) -> tuple[WhatsAppMessageLogModel, _WhatsAppComposerSnapshot]:
    """Select the requested immutable send, retaining legacy latest-send behaviour."""
    from fastapi import status

    from app.presentation.api.v1.routes.whatsapp_composer_support import _composer_snapshot_from_log

    source_result = await session.execute(
        select(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.broadcast_group_id == group_id,
            WhatsAppMessageLogModel.recipient_id == recipient_id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.status.in_(
                WHATSAPP_ACCEPTED_STATUSES
                | ({"failed"} if is_retry or source_message_log_id else set())
            ),
            *(
                [WhatsAppMessageLogModel.id == source_message_log_id]
                if source_message_log_id is not None
                else []
            ),
        )
        .order_by(
            WhatsAppMessageLogModel.created_at.desc(),
            WhatsAppMessageLogModel.status_updated_at.desc(),
        )
        .limit(1)
    )
    source_log = source_result.scalar_one_or_none()
    if not source_log:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The previously saved WhatsApp message could not be found",
        )
    try:
        source_snapshot = _composer_snapshot_from_log(source_log)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This older WhatsApp message cannot be safely reconstructed for resend. "
                "Send a fresh message from the normal preview instead."
            ),
        ) from exc

    return source_log, source_snapshot


async def saved_template_name(
    session: AsyncSession,
    message_type: str,
    body: WhatsAppResendRequest,
    source_log: WhatsAppMessageLogModel,
) -> str:
    from app.infrastructure.whatsapp.template_settings import configured_template_name

    if body.source_message_log_id is not None and source_log.template_name:
        return source_log.template_name
    return await configured_template_name(session, message_type)


def frozen_resend_values(
    body: WhatsAppResendRequest,
    source_log: WhatsAppMessageLogModel,
    template_name: str,
    headers: list[str],
    parameters: list[str],
    rendered_message: str | None,
) -> tuple[str, list[str], list[str], str | None]:
    from app.presentation.api.v1.routes.whatsapp_composer_support import _template_snapshot_from_log

    if body.source_message_log_id is not None:
        headers, parameters = _template_snapshot_from_log(source_log)
        return (
            source_log.template_name or template_name,
            headers,
            parameters,
            source_log.rendered_message,
        )
    return template_name, headers, parameters, rendered_message
