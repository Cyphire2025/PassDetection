"""Claim existing delivery rows and preserve stale, uncertain and phone history rules."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import Insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.message_templates import WhatsAppMessageType
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp.group_invite_policy import (
    group_invite_blocking_statuses,
    group_invite_skip_reason,
    message_phone_blocking_statuses,
)
from app.presentation.api.v1.routes.whatsapp_phone_welcome import claim_broadcast_welcome_phones
from app.presentation.api.v1.routes.whatsapp_recipient_claims import claim_broadcast_recipient_rows
from app.presentation.api.v1.routes.whatsapp_roster_support import (
    _active_explicit_reminder_recipient_ids,
)
from app.presentation.api.v1.routes.whatsapp_send_support import (
    release_stale_broadcast_claims,
    send_suppression_statuses,
    unclaimed_delivery_counts,
)
from app.presentation.api.v1.routes.whatsapp_shared import WHATSAPP_STALE_CLAIM_AGE
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppSendRequest


@dataclass(frozen=True, slots=True)
class ClaimedBroadcastSend:
    claimed_recipients: list[WhatsAppBroadcastRecipientModel]
    welcome_log_ids: dict[uuid.UUID, uuid.UUID]
    skipped_already_sent: int
    skipped_in_progress: int
    skipped_delivery_unknown: int


async def claim_prepared_broadcast_send(
    session: AsyncSession,
    *,
    group: WhatsAppBroadcastGroupModel,
    recipients: list[WhatsAppBroadcastRecipientModel],
    body: WhatsAppSendRequest,
    message_type: WhatsAppMessageType,
    batch_id: uuid.UUID,
    now: datetime,
    suppress_unknown_reminders: bool,
    insert_factory: Callable[[type[WhatsAppRecipientMessageStateModel]], Insert],
) -> ClaimedBroadcastSend:
    stale_cutoff = now - WHATSAPP_STALE_CLAIM_AGE
    suppressed_statuses = send_suppression_statuses(
        message_type, suppress_unknown_reminders, body.include_previous_recipients
    )
    if suppress_unknown_reminders:
        recorded_states = await session.scalars(
            select(WhatsAppRecipientMessageStateModel.status)
            .where(
                WhatsAppRecipientMessageStateModel.recipient_id.in_(
                    [recipient.id for recipient in recipients]
                ),
                WhatsAppRecipientMessageStateModel.message_type == message_type,
            )
            .distinct()
        )
        suppressed_statuses |= frozenset(recorded_states.all()) - {
            "submitted",
            "sent",
            "delivered",
            "read",
            "failed",
        }
    await release_stale_broadcast_claims(
        session, group_id=group.id, message_type=message_type, now=now, stale_cutoff=stale_cutoff
    )

    active_explicit_reminder_ids = (
        await _active_explicit_reminder_recipient_ids(session, recipients, message_type)
        if message_type in {"reminder", "update"}
        else set()
    )
    if message_type == "passport_link":
        # Its phone-history guard also reads the baseline ledger. Release the
        # same stale, unsubmitted claim that the upsert formerly reclaimed.
        await session.execute(
            update(WhatsAppRecipientMessageStateModel)
            .where(
                WhatsAppRecipientMessageStateModel.broadcast_group_id == group.id,
                WhatsAppRecipientMessageStateModel.message_type == message_type,
                WhatsAppRecipientMessageStateModel.status == "queued",
                WhatsAppRecipientMessageStateModel.status_updated_at < stale_cutoff,
            )
            .values(status="failed", batch_id=None, status_updated_at=now, updated_at=now)
            .execution_options(synchronize_session=False)
        )
    invite_blocks = (
        await group_invite_blocking_statuses(session, recipients)
        if message_type == "group_invite"
        else await message_phone_blocking_statuses(
            session,
            recipients,
            message_type=message_type,
            include_accepted=not body.include_previous_recipients,
        )
        if message_type == "passport_link"
        else {}
    )
    claimed_recipient_ids = await claim_broadcast_recipient_rows(
        session,
        group_id=group.id,
        recipients=recipients,
        message_type=message_type,
        batch_id=batch_id,
        now=now,
        stale_cutoff=stale_cutoff,
        active_explicit_reminder_ids=active_explicit_reminder_ids,
        invite_blocks=invite_blocks,
        suppressed_statuses=suppressed_statuses,
        insert_factory=insert_factory,
    )
    claimed_recipients = [
        recipient for recipient in recipients if recipient.id in claimed_recipient_ids
    ]
    (
        claimed_recipients,
        welcome_log_ids,
        phone_skipped_already,
        phone_skipped_progress,
        phone_skipped_unknown,
    ) = await claim_broadcast_welcome_phones(
        session,
        agency_id=group.agency_id,
        message_type=message_type,
        recipients=claimed_recipients,
        batch_id=batch_id,
        now=now,
    )
    unclaimed_recipient_ids = [
        recipient.id
        for recipient in recipients
        if recipient.id not in claimed_recipient_ids
        and recipient.id not in active_explicit_reminder_ids
        and recipient.id not in invite_blocks
    ]
    (
        skipped_already_sent,
        skipped_in_progress,
        skipped_delivery_unknown,
    ) = await unclaimed_delivery_counts(
        session,
        recipient_ids=unclaimed_recipient_ids,
        message_type=message_type,
    )
    skipped_in_progress += len(active_explicit_reminder_ids)
    invite_reasons = [group_invite_skip_reason(value) for value in invite_blocks.values()]
    skipped_already_sent += invite_reasons.count("skipped_already_sent")
    skipped_in_progress += invite_reasons.count("skipped_in_progress")
    skipped_delivery_unknown += invite_reasons.count("skipped_delivery_unknown")
    skipped_already_sent += phone_skipped_already
    skipped_in_progress += phone_skipped_progress
    skipped_delivery_unknown += phone_skipped_unknown
    return ClaimedBroadcastSend(
        claimed_recipients=claimed_recipients,
        welcome_log_ids=welcome_log_ids,
        skipped_already_sent=skipped_already_sent,
        skipped_in_progress=skipped_in_progress,
        skipped_delivery_unknown=skipped_delivery_unknown,
    )
