"""Serialize duplicate-worker observations with a live provider attempt."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import Settings
from app.infrastructure.database.models import WhatsAppBroadcastGroupModel, WhatsAppMessageLogModel
from app.infrastructure.whatsapp.mcp_dispatch import authorize_mcp_batch_dispatch


async def lock_interrupted_broadcast_log(
    session: AsyncSession, identifier: uuid.UUID, settings: Settings
) -> WhatsAppMessageLogModel | None:
    initial = await session.get(WhatsAppMessageLogModel, identifier, populate_existing=True)
    if initial is None:
        return None
    # Reconciliation is not a new send and must preserve observations even when
    # authority has gone. Acquiring the dispatch locks still ensures a currently
    # live attempt commits its receipt before a duplicate can mark it unknown.
    await authorize_mcp_batch_dispatch(session, log=initial, settings=settings)
    await session.scalar(
        select(WhatsAppBroadcastGroupModel.id)
        .where(
            WhatsAppBroadcastGroupModel.id == initial.broadcast_group_id,
        )
        .with_for_update()
    )
    row: WhatsAppMessageLogModel | None = await session.scalar(
        select(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.id == identifier,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return row
