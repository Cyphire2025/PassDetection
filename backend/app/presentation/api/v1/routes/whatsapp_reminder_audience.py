"""Server-authoritative audience resolution for WhatsApp reminders."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    load_unresolved_passport_whatsapp_match_context,
)
from app.presentation.api.v1.routes.whatsapp_group_visibility import staff_linked_group_filters


@dataclass(frozen=True, slots=True)
class ReminderAudienceResolution:
    recipients: tuple[WhatsAppBroadcastRecipientModel, ...]
    audience: str
    client_group_id: uuid.UUID | None
    source_recipient_count: int
    excluded_submitted_count: int = 0
    excluded_needs_review_count: int = 0


async def resolve_reminder_audience(
    session: AsyncSession,
    *,
    broadcast_group: WhatsAppBroadcastGroupModel,
    recipients: list[WhatsAppBroadcastRecipientModel],
    audience: str,
    audience_client_group_id: uuid.UUID | None,
    current_user: User,
) -> ReminderAudienceResolution:
    """Resolve one reminder scope without taking locks after the broadcast lock.

    Matching is calculated across every WhatsApp broadcast linked to the chosen
    upload group. The final set is then intersected with this broadcast's live
    recipients, so the same person cannot receive a reminder merely because
    their equivalent row in another linked list carried the successful match.
    """

    source_count = len(recipients)
    if audience == "all":
        return ReminderAudienceResolution(
            recipients=tuple(recipients),
            audience="all",
            client_group_id=None,
            source_recipient_count=source_count,
        )

    linked_statement = (
        select(ClientGroupModel.id)
        .join(
            ClientGroupWhatsAppBroadcastLinkModel,
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == ClientGroupModel.id,
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id == broadcast_group.id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == broadcast_group.agency_id,
            ClientGroupModel.agency_id == broadcast_group.agency_id,
            ClientGroupModel.status == "active",
            ClientGroupModel.deleted_at.is_(None),
        )
        .order_by(ClientGroupModel.id)
    )
    if audience_client_group_id is not None:
        linked_statement = linked_statement.where(ClientGroupModel.id == audience_client_group_id)
    linked_ids = list((await session.execute(linked_statement)).scalars().all())
    linked_ids = list(dict.fromkeys(linked_ids))
    if audience_client_group_id is not None and not linked_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "The selected upload group is not an active group linked to "
                "this WhatsApp broadcast."
            ),
        )
    if not linked_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Link this WhatsApp broadcast to an active upload group before "
                "sending a not-submitted reminder."
            ),
        )
    if len(linked_ids) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Choose which linked upload group should define the "
                "not-submitted reminder audience."
            ),
        )
    client_group_id = linked_ids[0]
    if current_user.role == UserRole.AGENCY_STAFF:
        accessible_group = await session.execute(
            select(ClientGroupModel.id).where(
                ClientGroupModel.id == client_group_id,
                *staff_linked_group_filters(current_user),
            )
        )
        if accessible_group.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to the upload group for this reminder audience.",
            )
    (
        _linked,
        _recipient_models,
        _submissions,
        match_rows,
    ) = await load_unresolved_passport_whatsapp_match_context(
        session,
        group_id=client_group_id,
        agency_id=broadcast_group.agency_id,
    )
    not_submitted_recipient_ids = {
        recipient_id
        for row in match_rows
        if row.status == "not_submitted"
        for recipient_id in row.recipient_ids
    }
    submitted_recipient_ids = {
        recipient_id
        for row in match_rows
        if row.status in {"submitted", "multiple_submissions"}
        for recipient_id in row.recipient_ids
    }
    review_recipient_ids = {
        recipient_id
        for row in match_rows
        if row.status == "needs_review"
        for recipient_id in row.recipient_ids
    }
    selected = tuple(
        recipient for recipient in recipients if recipient.id in not_submitted_recipient_ids
    )
    if not selected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Everyone in this WhatsApp broadcast has either submitted or "
                "requires identity review; there is no not-submitted audience."
            ),
        )
    selected_ids = {recipient.id for recipient in selected}
    source_ids = {recipient.id for recipient in recipients}
    submitted_ids = source_ids & submitted_recipient_ids
    review_ids = source_ids & review_recipient_ids
    # Any unexpected unmatched category is kept out of a reminder and exposed
    # as review, rather than silently treating uncertain identity as missing.
    review_ids |= source_ids - selected_ids - submitted_ids - review_ids
    return ReminderAudienceResolution(
        recipients=selected,
        audience="not_submitted",
        client_group_id=client_group_id,
        source_recipient_count=source_count,
        excluded_submitted_count=len(submitted_ids),
        excluded_needs_review_count=len(review_ids),
    )
