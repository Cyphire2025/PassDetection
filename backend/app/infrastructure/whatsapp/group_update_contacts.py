"""Materialize a submitted destination only after the user confirms a send."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.recipient_capacity import MAX_WHATSAPP_RECIPIENTS
from app.infrastructure.database.models import WhatsAppBroadcastRecipientModel


async def ensure_group_update_recipient(
    session: AsyncSession, *, agency_id: uuid.UUID, broadcast_id: uuid.UUID,
    name: str, phone: str,
) -> uuid.UUID:
    """The caller holds the broadcast lock. Never revive a removed contact.

    Message history requires a delivery recipient. This appends that contact for
    a completed submission's own phone, without changing any existing number,
    passport, identity match, document or imported Excel data.
    """
    existing = await session.scalar(select(WhatsAppBroadcastRecipientModel).where(
        WhatsAppBroadcastRecipientModel.agency_id == agency_id,
        WhatsAppBroadcastRecipientModel.broadcast_group_id == broadcast_id,
        WhatsAppBroadcastRecipientModel.normalized_phone_number == phone,
    ).with_for_update())
    if existing:
        if (existing.removed_at is not None or existing.merged_into_recipient_id is not None
                or existing.suppressed_by_roster_resolution_id is not None):
            raise ValueError("This WhatsApp contact was removed or replaced. Restore it before sending.")
        return existing.id
    count, last_order = (await session.execute(select(
        func.count(), func.max(WhatsAppBroadcastRecipientModel.display_order),
    ).where(
        WhatsAppBroadcastRecipientModel.agency_id == agency_id,
        WhatsAppBroadcastRecipientModel.broadcast_group_id == broadcast_id,
        WhatsAppBroadcastRecipientModel.removed_at.is_(None),
    ))).one()
    if count >= MAX_WHATSAPP_RECIPIENTS:
        raise ValueError("The linked broadcast is full. Free a contact slot before sending.")
    recipient = WhatsAppBroadcastRecipientModel(
        id=uuid.uuid4(), agency_id=agency_id, broadcast_group_id=broadcast_id,
        name=name[:255], phone_number=phone, normalized_phone_number=phone,
        imported_fields={}, display_order=(last_order or 0) + 1,
        is_source_managed=False, created_at=datetime.now(UTC),
    )
    session.add(recipient)
    await session.flush()
    return recipient.id
