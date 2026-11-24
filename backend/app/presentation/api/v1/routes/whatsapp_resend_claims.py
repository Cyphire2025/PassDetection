"""Retain baseline/unknown-delivery and phone prerequisites for one resend."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.message_templates import WhatsAppMessageType
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp.group_invite_policy import (
    group_invite_block_message,
    group_invite_blocking_statuses,
    message_phone_blocking_statuses,
    passport_link_block_message,
)
from app.presentation.api.v1.routes.whatsapp_phone_welcome import (
    enforce_broadcast_welcome_prerequisite,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ACCEPTED_STATUSES,
    WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES,
    WHATSAPP_STALE_CLAIM_AGE,
)


@dataclass(frozen=True)
class ResendClaim:
    delivery_state: WhatsAppRecipientMessageStateModel
    is_retry: bool
    now: datetime


async def read_resend_claim(
    session: AsyncSession,
    group: WhatsAppBroadcastGroupModel,
    recipient: WhatsAppBroadcastRecipientModel,
    message_type: WhatsAppMessageType,
) -> ResendClaim:
    if message_type == "group_invite":
        invite_blocks = await group_invite_blocking_statuses(session, [recipient])
        if recipient.id in invite_blocks:
            raise HTTPException(
                status_code=409, detail=group_invite_block_message(invite_blocks[recipient.id])
            )
    await enforce_broadcast_welcome_prerequisite(
        session,
        agency_id=group.agency_id,
        message_type=message_type,
        recipients=[recipient],
    )
    state_result = await session.execute(
        select(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.recipient_id == recipient.id,
            WhatsAppRecipientMessageStateModel.message_type == message_type,
        )
        .with_for_update()
    )
    delivery_state = state_result.scalar_one_or_none()
    is_retry = bool(delivery_state and delivery_state.status == "failed")
    if not delivery_state or (
        delivery_state.status not in WHATSAPP_ACCEPTED_STATUSES and not is_retry
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Only a successfully submitted message can be resent, and only a "
                "failed message can be retried."
            ),
        )
    now = datetime.now(tz=UTC)
    stale_cutoff = now - WHATSAPP_STALE_CLAIM_AGE
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            WhatsAppMessageLogModel.status == "queued",
            WhatsAppMessageLogModel.message_type != "group_invite",
            WhatsAppMessageLogModel.status_updated_at < stale_cutoff,
        )
        .values(
            status="failed",
            status_updated_at=now,
            error_message="Explicit resend claim expired before provider submission",
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            WhatsAppMessageLogModel.status == "processing",
            WhatsAppMessageLogModel.status_updated_at < stale_cutoff,
        )
        .values(
            status="delivery_unknown",
            status_updated_at=now,
            error_message=(
                "Explicit resend outcome is unknown after a worker interruption; "
                "another resend is blocked"
            ),
        )
        .execution_options(synchronize_session=False)
    )
    active_resend_result = await session.execute(
        select(WhatsAppMessageLogModel).where(
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            WhatsAppMessageLogModel.status.in_(WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES),
        )
    )
    active_resend = active_resend_result.scalar_one_or_none()
    if active_resend:
        detail = (
            "The previous resend has an unknown delivery outcome. "
            "Verify it with the recipient before attempting another resend."
            if active_resend.status == "delivery_unknown"
            else "A resend of this message is already in progress for this recipient."
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        )
    if message_type == "passport_link":
        phone_blocks = await message_phone_blocking_statuses(
            session,
            [recipient],
            message_type=message_type,
            include_accepted=is_retry,
        )
        if recipient.id in phone_blocks:
            raise HTTPException(
                status_code=409,
                detail=passport_link_block_message(phone_blocks[recipient.id]),
            )
    return ResendClaim(delivery_state, is_retry, now)
