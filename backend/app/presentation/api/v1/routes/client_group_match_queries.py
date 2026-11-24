"""Match Queries for upload links; HTTP declarations remain in client_groups."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.group_submission_matching import (
    SubmissionMatchRow,
)
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportSubmissionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    load_unresolved_passport_whatsapp_match_context,
    matching_field_keys_from_storage,
)


async def _linked_broadcast_names_for_group(
    session: AsyncSession, *, group_id: uuid.UUID, agency_id: uuid.UUID
) -> dict[uuid.UUID, str]:
    result = await session.execute(
        select(
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
            WhatsAppBroadcastGroupModel.name,
        )
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id
            == ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group_id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
            WhatsAppBroadcastGroupModel.agency_id == agency_id,
        )
    )
    return {broadcast_id: broadcast_name for broadcast_id, broadcast_name in result.all()}


async def _linked_broadcast_matching_fields_for_group(
    session: AsyncSession, *, group_id: uuid.UUID, agency_id: uuid.UUID
) -> dict[uuid.UUID, tuple[str, ...] | None]:
    result = await session.execute(
        select(
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
            ClientGroupWhatsAppBroadcastLinkModel.matching_field_keys,
        ).where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group_id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
        )
    )
    return {
        broadcast_id: matching_field_keys_from_storage(matching_field_keys)
        for broadcast_id, matching_field_keys in result.all()
    }


async def _current_unresolved_match_context(
    session: AsyncSession, *, group_id: uuid.UUID, agency_id: uuid.UUID
) -> tuple[
    dict[uuid.UUID, str],
    list[WhatsAppBroadcastRecipientModel],
    list[PassportSubmissionModel],
    list[SubmissionMatchRow],
]:
    return await load_unresolved_passport_whatsapp_match_context(
        session,
        group_id=group_id,
        agency_id=agency_id,
    )
