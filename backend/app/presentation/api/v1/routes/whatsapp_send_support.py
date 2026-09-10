"""Delivery-claim response accounting shared by broadcast send paths."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import WhatsAppRecipientMessageStateModel
from app.presentation.api.v1.routes.whatsapp_delivery_support import (
    WHATSAPP_ACCEPTED_STATUSES,
    WHATSAPP_IN_PROGRESS_STATUSES,
    WHATSAPP_UNCERTAIN_STATUSES,
)


async def unclaimed_delivery_counts(
    session: AsyncSession,
    *,
    recipient_ids: list[uuid.UUID],
    message_type: str,
) -> tuple[int, int, int]:
    """Count accepted, active, and uncertain claims without changing eligibility."""
    if not recipient_ids:
        return 0, 0, 0
    result = await session.execute(
        select(WhatsAppRecipientMessageStateModel.status).where(
            WhatsAppRecipientMessageStateModel.recipient_id.in_(recipient_ids),
            WhatsAppRecipientMessageStateModel.message_type == message_type,
        )
    )
    statuses = list(result.scalars().all())
    return (
        sum(delivery_status in WHATSAPP_ACCEPTED_STATUSES for delivery_status in statuses),
        sum(delivery_status in WHATSAPP_IN_PROGRESS_STATUSES for delivery_status in statuses),
        sum(delivery_status in WHATSAPP_UNCERTAIN_STATUSES for delivery_status in statuses),
    )
