"""Persistence helpers for durable passport-roster replacement suppression."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportRosterResolutionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)


async def lock_whatsapp_broadcast_groups(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    broadcast_group_ids: list[uuid.UUID] | set[uuid.UUID] | tuple[uuid.UUID, ...],
) -> list[uuid.UUID]:
    """Lock broadcast rows in stable order and return the rows that still exist."""

    group_ids = sorted(set(broadcast_group_ids), key=str)
    if not group_ids:
        return []
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel.id)
        .where(
            WhatsAppBroadcastGroupModel.id.in_(group_ids),
            WhatsAppBroadcastGroupModel.agency_id == agency_id,
        )
        .order_by(WhatsAppBroadcastGroupModel.id.asc())
        .with_for_update()
    )
    return list(result.scalars().all())


async def active_replacement_phone_numbers_for_broadcast(
    session: AsyncSession,
    *,
    broadcast_group_id: uuid.UUID,
    agency_id: uuid.UUID,
) -> set[str]:
    """Return phone identities excluded by active linked-group replacements."""

    result = await session.execute(
        select(PassportRosterResolutionModel.replaced_recipient_normalized_phone)
        .join(
            ClientGroupWhatsAppBroadcastLinkModel,
            and_(
                ClientGroupWhatsAppBroadcastLinkModel.client_group_id
                == PassportRosterResolutionModel.client_group_id,
                ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id == broadcast_group_id,
                ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
            ),
        )
        .where(
            PassportRosterResolutionModel.agency_id == agency_id,
            PassportRosterResolutionModel.status == "active",
            PassportRosterResolutionModel.resolution_type == "replacement",
        )
        .distinct()
    )
    return {
        normalized_phone
        for normalized_phone in result.scalars().all()
        if normalized_phone is not None
    }


async def active_replacement_resolution_id_for_recipient(
    session: AsyncSession,
    *,
    recipient: WhatsAppBroadcastRecipientModel,
) -> uuid.UUID | None:
    """Resolve the active replacement that excludes a recipient at send time."""

    result = await session.execute(
        select(PassportRosterResolutionModel.id)
        .join(
            ClientGroupWhatsAppBroadcastLinkModel,
            and_(
                ClientGroupWhatsAppBroadcastLinkModel.client_group_id
                == PassportRosterResolutionModel.client_group_id,
                ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id
                == recipient.broadcast_group_id,
                ClientGroupWhatsAppBroadcastLinkModel.agency_id == recipient.agency_id,
            ),
        )
        .where(
            PassportRosterResolutionModel.agency_id == recipient.agency_id,
            PassportRosterResolutionModel.status == "active",
            PassportRosterResolutionModel.resolution_type == "replacement",
            PassportRosterResolutionModel.replaced_recipient_normalized_phone
            == recipient.normalized_phone_number,
        )
        .order_by(
            PassportRosterResolutionModel.created_at.asc(),
            PassportRosterResolutionModel.id.asc(),
        )
        .limit(1)
    )
    return result.scalar_one_or_none()


async def suppress_active_replacement_recipients(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    broadcast_group_ids: list[uuid.UUID] | set[uuid.UUID] | tuple[uuid.UUID, ...],
    now: datetime,
) -> list[WhatsAppBroadcastRecipientModel]:
    """Suppress active rows whose phone is replaced in any linked passport group.

    Broadcast rows are locked in stable order so imports, link changes, sends, and
    worker checks serialize around the same boundary.
    """

    group_ids = sorted(set(broadcast_group_ids), key=str)
    if not group_ids:
        return []

    await lock_whatsapp_broadcast_groups(
        session,
        agency_id=agency_id,
        broadcast_group_ids=group_ids,
    )

    candidate_recipient = aliased(WhatsAppBroadcastRecipientModel)
    matches_result = await session.execute(
        select(candidate_recipient, PassportRosterResolutionModel)
        .join(
            ClientGroupWhatsAppBroadcastLinkModel,
            and_(
                ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id
                == candidate_recipient.broadcast_group_id,
                ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
            ),
        )
        .join(
            PassportRosterResolutionModel,
            and_(
                PassportRosterResolutionModel.client_group_id
                == ClientGroupWhatsAppBroadcastLinkModel.client_group_id,
                PassportRosterResolutionModel.agency_id == agency_id,
            ),
        )
        .where(
            candidate_recipient.agency_id == agency_id,
            candidate_recipient.broadcast_group_id.in_(group_ids),
            candidate_recipient.removed_at.is_(None),
            candidate_recipient.suppressed_by_roster_resolution_id.is_(None),
            PassportRosterResolutionModel.status == "active",
            PassportRosterResolutionModel.resolution_type == "replacement",
            candidate_recipient.normalized_phone_number
            == PassportRosterResolutionModel.replaced_recipient_normalized_phone,
        )
        .order_by(
            PassportRosterResolutionModel.created_at.asc(),
            PassportRosterResolutionModel.id.asc(),
            candidate_recipient.id.asc(),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )

    selected_by_recipient: dict[
        uuid.UUID,
        tuple[WhatsAppBroadcastRecipientModel, PassportRosterResolutionModel],
    ] = {}
    for recipient, resolution in matches_result.all():
        selected_by_recipient.setdefault(recipient.id, (recipient, resolution))
    if not selected_by_recipient:
        return []

    touched_resolutions: dict[uuid.UUID, PassportRosterResolutionModel] = {}
    suppressed: list[WhatsAppBroadcastRecipientModel] = []
    for recipient, resolution in selected_by_recipient.values():
        recipient.removed_at = now
        recipient.suppressed_by_roster_resolution_id = resolution.id
        touched_resolutions[resolution.id] = resolution
        suppressed.append(recipient)

    suppressed_ids = [recipient.id for recipient in suppressed]
    for resolution in touched_resolutions.values():
        existing_ids = list(resolution.suppressed_recipient_ids or [])
        additions = [
            str(recipient.id)
            for recipient in suppressed
            if recipient.suppressed_by_roster_resolution_id == resolution.id
        ]
        resolution.suppressed_recipient_ids = list(dict.fromkeys([*existing_ids, *additions]))

    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.recipient_id.in_(suppressed_ids),
            WhatsAppMessageLogModel.status == "queued",
        )
        .values(
            status="failed",
            status_updated_at=now,
            error_message=("Recipient replaced in linked passport group before delivery"),
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.recipient_id.in_(suppressed_ids),
            WhatsAppRecipientMessageStateModel.status == "queued",
        )
        .values(
            status="failed",
            batch_id=None,
            status_updated_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppBroadcastGroupModel)
        .where(WhatsAppBroadcastGroupModel.id.in_(group_ids))
        .values(updated_at=now)
        .execution_options(synchronize_session=False)
    )
    return suppressed
