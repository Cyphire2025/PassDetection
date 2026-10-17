"""Re-evaluate update filters on the server for preview and dispatch."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.domain.whatsapp_delivery_status import WHATSAPP_ACCEPTED_STATUSES
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    DistributedDocumentModel,
    DocumentWhatsAppDeliveryModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    load_unresolved_passport_whatsapp_match_context,
)
from app.presentation.api.v1.routes.whatsapp_group_visibility import staff_linked_group_filters

if TYPE_CHECKING:
    from app.presentation.api.v1.routes.whatsapp_reminder_audience import ReminderAudienceResolution
    from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppSendRequest


async def completed_document_submissions(
    session: AsyncSession,
    group_ids: list[UUID],
    agency_id: UUID,
    document_type: str,
) -> set[UUID]:
    """A partially sent multi-PDF assignment is pending, never completed."""
    expected: dict[UUID, set[UUID]] = defaultdict(set)
    documents = await session.execute(
        select(
            DistributedDocumentModel.passenger_id,
            DistributedDocumentModel.id,
        ).where(
            DistributedDocumentModel.group_id.in_(group_ids),
            DistributedDocumentModel.agency_id == agency_id,
            DistributedDocumentModel.document_type == document_type,
            DistributedDocumentModel.match_status == "matched",
            DistributedDocumentModel.passenger_id.is_not(None),
        )
    )
    for passenger_id, document_id in documents:
        expected[passenger_id].add(document_id)
    deliveries = await session.execute(
        select(
            DocumentWhatsAppDeliveryModel.passenger_id,
            DocumentWhatsAppDeliveryModel.distributed_document_id,
            DocumentWhatsAppDeliveryModel.status,
        )
        .where(
            DocumentWhatsAppDeliveryModel.group_id.in_(group_ids),
            DocumentWhatsAppDeliveryModel.agency_id == agency_id,
            DocumentWhatsAppDeliveryModel.document_type == document_type,
        )
        .order_by(
            DocumentWhatsAppDeliveryModel.created_at.desc(), DocumentWhatsAppDeliveryModel.id.desc()
        )
    )
    latest: dict[tuple[UUID, UUID], str] = {}
    for passenger_id, document_id, status in deliveries:
        if passenger_id is not None and document_id is not None:
            latest.setdefault((passenger_id, document_id), status)
    return {
        passenger_id
        for passenger_id, document_ids in expected.items()
        if all(
            latest.get((passenger_id, document_id)) in WHATSAPP_ACCEPTED_STATUSES
            for document_id in document_ids
        )
    }


async def resolve_update_audience(
    session: AsyncSession,
    *,
    broadcast_group: WhatsAppBroadcastGroupModel,
    recipients: list[WhatsAppBroadcastRecipientModel],
    roster: list[WhatsAppBroadcastRecipientModel],
    body: WhatsAppSendRequest,
    current_user: User,
) -> ReminderAudienceResolution:
    from app.presentation.api.v1.routes.whatsapp_reminder_audience import ReminderAudienceResolution

    linked = await session.scalars(
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
            *staff_linked_group_filters(current_user),
        )
        .order_by(ClientGroupModel.id)
    )
    group_ids = list(dict.fromkeys(linked.all()))
    if not group_ids:
        raise HTTPException(
            409, "Link an accessible, active trip group to use document audience filters."
        )
    delivered = (
        await completed_document_submissions(
            session,
            group_ids,
            broadcast_group.agency_id,
            body.update_document_type,
        )
        if body.update_distribution != "all"
        else set()
    )
    allowed: set[UUID] = set()
    for group_id in group_ids:
        _, _, _, matches = await load_unresolved_passport_whatsapp_match_context(
            session,
            group_id=group_id,
            agency_id=broadcast_group.agency_id,
        )
        for row in matches:
            submitted = row.status in {"submitted", "multiple_submissions"}
            if row.status not in {"submitted", "multiple_submissions", "not_submitted"}:
                continue
            if body.update_submission == "submitted" and not submitted:
                continue
            if body.update_submission == "not_submitted" and submitted:
                continue
            all_sent = bool(row.submission_ids) and all(
                item in delivered for item in row.submission_ids
            )
            if body.update_distribution == "sent" and not all_sent:
                continue
            if body.update_distribution == "pending" and all_sent:
                continue
            allowed.update(row.recipient_ids)
    return ReminderAudienceResolution(
        recipients=tuple(item for item in recipients if item.id in allowed),
        audience="all",
        client_group_id=None,
        source_recipient_count=len(recipients),
        selectable_recipient_ids=tuple(item.id for item in roster if item.id in allowed),
    )
