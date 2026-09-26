"""Atomically claim eligible broadcast recipient ledger rows."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import and_, literal, or_
from sqlalchemy.dialects.postgresql import Insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel,
    WhatsAppRecipientMessageStateModel,
)


async def claim_broadcast_recipient_rows(
    session: AsyncSession, *, group_id: uuid.UUID, recipients: list[WhatsAppBroadcastRecipientModel],
    message_type: str, batch_id: uuid.UUID, now: datetime, stale_cutoff: datetime,
    active_explicit_reminder_ids: set[uuid.UUID], invite_blocks: dict[uuid.UUID, str],
    suppressed_statuses: set[str] | frozenset[str],
    insert_factory: Callable[[type[WhatsAppRecipientMessageStateModel]], Insert],
) -> set[uuid.UUID]:
    claim_values = [
        {
            "id": uuid.uuid4(),
            "broadcast_group_id": group_id,
            "recipient_id": recipient.id,
            "agency_id": recipient.agency_id,
            "message_type": message_type,
            "status": "queued",
            "batch_id": batch_id,
            "submitted_at": None,
            "status_updated_at": now,
            "created_at": now,
            "updated_at": now,
        }
        for recipient in recipients
        if recipient.id not in active_explicit_reminder_ids
        and recipient.id not in invite_blocks
    ]
    claimed_recipient_ids: set[uuid.UUID] = set()
    if claim_values:
        claim_insert = insert_factory(WhatsAppRecipientMessageStateModel).values(claim_values)
        claim_statement = (
            claim_insert.on_conflict_do_update(
                constraint="uq_whatsapp_recipient_message_state",
                set_={
                    "status": "queued",
                    "batch_id": batch_id,
                    "submitted_at": None,
                    "status_updated_at": now,
                    "updated_at": now,
                    **({"provider_status_at": None} if message_type == "reminder" else {}),
                },
                where=or_(
                    ~WhatsAppRecipientMessageStateModel.status.in_(suppressed_statuses),
                    and_(
                        literal(message_type != "group_invite"),
                        WhatsAppRecipientMessageStateModel.status == "queued",
                        WhatsAppRecipientMessageStateModel.status_updated_at < stale_cutoff,
                    ),
                ),
            )
            .returning(WhatsAppRecipientMessageStateModel.recipient_id)
            .execution_options(synchronize_session=False)
        )
        claimed_result = await session.execute(claim_statement)
        claimed_recipient_ids = set(claimed_result.scalars().all())
    return claimed_recipient_ids
