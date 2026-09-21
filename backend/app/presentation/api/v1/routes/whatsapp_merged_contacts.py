"""Preserve manual contact identities behind a shared delivery destination."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import WhatsAppBroadcastRecipientModel as Recipient
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppMergedContactResponse


async def merged_contacts_by_recipient(
    session: AsyncSession, *, agency_id: uuid.UUID, broadcast_group_id: uuid.UUID,
) -> dict[uuid.UUID, list[WhatsAppMergedContactResponse]]:
    # Snapshots survive reuse of a removed recipient's former phone slot. Source
    # travellers have SourceContact rows; only independent manual contacts belong
    # here. Never flatten one person's imported fields into another's record.
    rows = (await session.scalars(select(Recipient).where(
        Recipient.agency_id == agency_id,
        Recipient.broadcast_group_id == broadcast_group_id,
        Recipient.merged_into_recipient_id.is_(None),
        Recipient.removed_at.is_(None),
    ).order_by(Recipient.display_order, Recipient.created_at, Recipient.id))).all()
    result: dict[uuid.UUID, list[WhatsAppMergedContactResponse]] = {}
    for row in rows:
        if row.merged_contacts:
            result[row.id] = [WhatsAppMergedContactResponse.model_validate(contact) for contact in row.merged_contacts]
    return result
