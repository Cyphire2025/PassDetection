"""Welcome prerequisites and atomic phone claims for the imported-list routes."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.welcome_policy import requires_prior_welcome
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp.phone_welcome import (
    WELCOME_DELIVERED_STATUSES,
    WELCOME_REQUIRED,
    claim_phone_welcome,
    sync_failed_broadcast_welcomes,
)


async def enforce_broadcast_welcome_prerequisite(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    message_type: str,
    recipients: Sequence[WhatsAppBroadcastRecipientModel],
) -> None:
    if not requires_prior_welcome(message_type):
        return
    from app.presentation.api.v1.routes.whatsapp_welcome_view import (
        phone_welcome_statuses_by_recipient,
    )
    states = await phone_welcome_statuses_by_recipient(session, list(recipients))
    if any(states.get(recipient.id) not in WELCOME_DELIVERED_STATUSES for recipient in recipients):
        raise HTTPException(status_code=409, detail=WELCOME_REQUIRED)


async def claim_broadcast_welcome_phones(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    message_type: str,
    recipients: list[WhatsAppBroadcastRecipientModel],
    batch_id: uuid.UUID,
    now: datetime,
) -> tuple[list[WhatsAppBroadcastRecipientModel], dict[uuid.UUID, uuid.UUID], int, int, int]:
    if message_type != "welcome":
        return recipients, {}, 0, 0, 0
    if recipients:
        await sync_failed_broadcast_welcomes(
            session, broadcast_group_id=recipients[0].broadcast_group_id
        )
    accepted: list[WhatsAppBroadcastRecipientModel] = []
    log_ids: dict[uuid.UUID, uuid.UUID] = {}
    already = pending = unknown = 0
    for recipient in sorted(recipients, key=lambda item: item.normalized_phone_number):
        log_id = uuid.uuid4()
        status = await claim_phone_welcome(
            session,
            agency_id=agency_id,
            phone=recipient.normalized_phone_number,
            attempt_id=log_id,
            attempt_kind="broadcast",
            broadcast_group_id=recipient.broadcast_group_id, batch_id=batch_id,
        )
        if status == "claimed":
            log_ids[recipient.id] = log_id
            accepted.append(recipient)
            continue
        already += int(status in {"submitted", "sent", "delivered", "read"})
        pending += int(status in {"queued", "processing"})
        unknown += int(status == "delivery_unknown")
        await session.execute(
            update(WhatsAppRecipientMessageStateModel)
            .where(
                WhatsAppRecipientMessageStateModel.recipient_id == recipient.id,
                WhatsAppRecipientMessageStateModel.message_type == "welcome",
                WhatsAppRecipientMessageStateModel.batch_id == batch_id,
            )
            .values(status="failed", batch_id=None, status_updated_at=now)
        )
    return accepted, log_ids, already, pending, unknown


async def claim_resend_welcome_or_reject(
    session: AsyncSession, log: WhatsAppMessageLogModel
) -> None:
    if log.message_type != "welcome":
        return
    assert log.normalized_phone_number is not None
    await sync_failed_broadcast_welcomes(session, broadcast_group_id=log.broadcast_group_id)
    status = await claim_phone_welcome(
        session,
        agency_id=log.agency_id,
        phone=log.normalized_phone_number,
        attempt_id=log.id,
        attempt_kind="broadcast",
        broadcast_group_id=log.broadcast_group_id, batch_id=log.batch_id,
        explicit_resend=log.is_explicit_resend,
    )
    if status != "claimed":
        raise HTTPException(
            status_code=409,
            detail=(
                "This WhatsApp number already has a welcome or welcome delivery is pending. "
                "Another welcome will not be sent."
            ),
        )
