"""Tenant-scoped roster sources for Rooming priority context construction."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    matching_field_keys_from_storage,
)


async def load_priority_broadcasts(
    session: AsyncSession, group: ClientGroupModel, *, lock_inputs: bool
) -> tuple[dict[uuid.UUID, str], dict[uuid.UUID, tuple[str, ...] | None]]:
    linked_statement = (
        select(
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
            WhatsAppBroadcastGroupModel.name,
            ClientGroupWhatsAppBroadcastLinkModel.matching_field_keys,
        )
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id
            == ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
            WhatsAppBroadcastGroupModel.agency_id == group.agency_id,
        )
    )
    if lock_inputs:
        linked_statement = linked_statement.with_for_update(read=True)
    linked_result = await session.execute(linked_statement)
    linked_rows = linked_result.all()
    linked_broadcasts: dict[uuid.UUID, str] = {
        broadcast_id: broadcast_name
        for broadcast_id, broadcast_name, _matching_fields in linked_rows
    }
    matching_fields_by_broadcast: dict[uuid.UUID, tuple[str, ...] | None] = {
        broadcast_id: matching_field_keys_from_storage(matching_fields)
        for broadcast_id, _broadcast_name, matching_fields in linked_rows
    }
    return linked_broadcasts, matching_fields_by_broadcast


async def load_priority_recipients(
    session: AsyncSession,
    group: ClientGroupModel,
    linked_broadcasts: dict[uuid.UUID, str],
    *,
    lock_inputs: bool,
) -> list[WhatsAppBroadcastRecipientModel]:
    recipient_statement = select(WhatsAppBroadcastRecipientModel).where(
        WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(linked_broadcasts),
        WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
        WhatsAppBroadcastRecipientModel.removed_at.is_(None),
    )
    if lock_inputs:
        recipient_statement = recipient_statement.with_for_update(read=True)
    recipient_result = await session.execute(recipient_statement)
    return list(recipient_result.scalars().all())
