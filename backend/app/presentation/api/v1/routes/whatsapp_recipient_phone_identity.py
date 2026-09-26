"""Delivery preconditions and identity-preserving recipient phone changes."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSourceContactModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES,
    WHATSAPP_IN_PROGRESS_STATUSES,
    WHATSAPP_UNCERTAIN_STATUSES,
)


async def require_recipient_phone_change_idle(
    session: AsyncSession, recipient: WhatsAppBroadcastRecipientModel,
    target: WhatsAppBroadcastRecipientModel | None,
) -> None:
    protected_recipient_ids = {recipient.id}
    if target is not None and target.removed_at is not None:
        protected_recipient_ids.add(target.id)
    active_state_result = await session.execute(
        select(WhatsAppRecipientMessageStateModel.id).where(
            WhatsAppRecipientMessageStateModel.recipient_id.in_(protected_recipient_ids),
            WhatsAppRecipientMessageStateModel.status.in_(
                WHATSAPP_IN_PROGRESS_STATUSES | WHATSAPP_UNCERTAIN_STATUSES
            ),
        )
    )
    if active_state_result.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Wait until the current delivery finishes, or review its unknown "
                "outcome, before changing this number"
            ),
        )
    active_log_result = await session.execute(
        select(WhatsAppMessageLogModel.id).where(
            WhatsAppMessageLogModel.recipient_id.in_(protected_recipient_ids),
            WhatsAppMessageLogModel.status.in_(WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES),
        )
    )
    if active_log_result.first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Wait until the current delivery finishes, or review its unknown "
                "outcome, before changing this number"
            ),
        )


async def apply_recipient_phone_identity(
    session: AsyncSession, *, group: WhatsAppBroadcastGroupModel,
    recipient: WhatsAppBroadcastRecipientModel, target: WhatsAppBroadcastRecipientModel | None,
    all_recipients: list[WhatsAppBroadcastRecipientModel], phone_number: str,
    normalized_phone: str, now: datetime,
) -> WhatsAppBroadcastRecipientModel:
    if target is not None:
        merged_contacts = list(target.merged_contacts or [])
        incoming_contacts = list(recipient.merged_contacts or [])
        canonical_source_identity = None
        if not recipient.is_source_managed:
            canonical_source_identity = await session.scalar(
                select(WhatsAppBroadcastSourceContactModel.id).where(
                    WhatsAppBroadcastSourceContactModel.agency_id == group.agency_id,
                    WhatsAppBroadcastSourceContactModel.broadcast_group_id == group.id,
                    WhatsAppBroadcastSourceContactModel.recipient_id == recipient.id,
                    WhatsAppBroadcastSourceContactModel.name == recipient.name,
                    WhatsAppBroadcastSourceContactModel.imported_fields == (recipient.imported_fields or {}),
                ).limit(1)
            )
        if not recipient.is_source_managed and canonical_source_identity is None:
            incoming_contacts.append({
                "id": str(uuid.uuid4()),
                "source_recipient_id": str(recipient.id),
                "name": recipient.name,
                "imported_fields": dict(recipient.imported_fields or {}),
            })
        for contact in incoming_contacts:
            # A reverse merge can reactivate this very identity. A recycled
            # phone slot holding another person must retain the old snapshot.
            same_target_identity = (
                contact.get("source_recipient_id") == str(target.id)
                and contact.get("name") == target.name
                and (contact.get("imported_fields") or {}) == (target.imported_fields or {})
            )
            if not same_target_identity:
                merged_contacts.append(contact)
        target.merged_contacts = merged_contacts
        recipient.merged_contacts = []
        target.removed_at = None
        target.merged_into_recipient_id = None
        target.is_source_managed = target.is_source_managed and recipient.is_source_managed
        recipient.removed_at = now
        recipient.merged_into_recipient_id = target.id
        # Existing redirects are flat. In particular, reactivating an old alias
        # must detach it before redirecting the old canonical row back to it.
        for alias in all_recipients:
            if alias.id != target.id and alias.merged_into_recipient_id == recipient.id:
                alias.merged_into_recipient_id = target.id
    else:
        target = recipient
        recipient.phone_number = phone_number.strip()
        recipient.normalized_phone_number = normalized_phone
        recipient.merged_into_recipient_id = None
        await session.execute(
            update(WhatsAppRecipientMessageStateModel)
            .where(WhatsAppRecipientMessageStateModel.recipient_id == recipient.id)
            .values(
                status="failed", batch_id=None, submitted_at=None,
                provider_status_at=None, status_updated_at=now, updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
    return target


async def mark_removed_recipient_messages(
    session: AsyncSession, recipient: WhatsAppBroadcastRecipientModel, now: datetime,
) -> None:
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.status == "queued",
        )
        .values(
            status="failed",
            status_updated_at=now,
            error_message="Recipient removed from WhatsApp broadcast before delivery",
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.recipient_id == recipient.id,
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
