"""Atomic persistence checks for the shared WhatsApp recipient-capacity policy."""

from __future__ import annotations

import uuid
from collections.abc import Collection, Mapping

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.recipient_capacity import (
    require_whatsapp_recipient_capacity,
)
from app.infrastructure.database.models import WhatsAppBroadcastRecipientModel


async def require_locked_broadcast_recipient_capacity(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    locked_broadcast_ids: Collection[uuid.UUID],
    activating_by_broadcast: Mapping[uuid.UUID, int],
) -> dict[uuid.UUID, int]:
    """Validate every requested activation after its broadcast row is locked.

    All capacity-changing routes serialize on the parent broadcast row. Requiring
    the caller to supply that locked set keeps the aggregate count and subsequent
    mutation in the same transaction without adding a second lock convention.
    """

    activating_counts = {
        broadcast_id: int(count)
        for broadcast_id, count in activating_by_broadcast.items()
        if count > 0
    }
    if not activating_counts:
        return {}

    locked_ids = set(locked_broadcast_ids)
    unlocked_ids = set(activating_counts) - locked_ids
    if unlocked_ids:
        raise RuntimeError("WhatsApp recipient capacity requires locked broadcast rows")

    result = await session.execute(
        select(
            WhatsAppBroadcastRecipientModel.broadcast_group_id,
            func.count(WhatsAppBroadcastRecipientModel.id),
        )
        .where(
            WhatsAppBroadcastRecipientModel.agency_id == agency_id,
            WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(activating_counts),
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
        .group_by(WhatsAppBroadcastRecipientModel.broadcast_group_id)
    )
    active_counts = {broadcast_id: int(count) for broadcast_id, count in result.all()}

    projected_counts: dict[uuid.UUID, int] = {}
    for broadcast_id in sorted(activating_counts, key=str):
        projected_counts[broadcast_id] = require_whatsapp_recipient_capacity(
            active_count=active_counts.get(broadcast_id, 0),
            activating_count=activating_counts[broadcast_id],
            broadcast_group_id=broadcast_id,
        )
    return projected_counts
