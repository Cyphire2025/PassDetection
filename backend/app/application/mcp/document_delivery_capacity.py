"""Bound canonical preview/dispatch hydration before loading its business rows."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    DistributedDocumentModel,
    DocumentWhatsAppDeliveryModel,
    PassportSubmissionModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastSourceContactModel,
)


async def document_delivery_within_capacity(
    session: AsyncSession, *, agency_id: uuid.UUID, group_id: uuid.UUID, document_type: str,
) -> bool:
    """Aggregate counts only; no unbounded models, document bytes or history hydration."""
    limits = [
        (select(func.count()).select_from(PassportSubmissionModel).where(
            PassportSubmissionModel.agency_id == agency_id, PassportSubmissionModel.group_id == group_id), 1500),
        (select(func.count()).select_from(DistributedDocumentModel).where(
            DistributedDocumentModel.agency_id == agency_id, DistributedDocumentModel.group_id == group_id,
            DistributedDocumentModel.document_type == document_type), 1500),
        (select(func.count()).select_from(DocumentWhatsAppDeliveryModel).where(
            DocumentWhatsAppDeliveryModel.agency_id == agency_id, DocumentWhatsAppDeliveryModel.group_id == group_id,
            DocumentWhatsAppDeliveryModel.document_type == document_type), 3000),
        (select(func.count()).select_from(ClientGroupWhatsAppBroadcastLinkModel).where(
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group_id), 10),
    ]
    for model in (WhatsAppBroadcastRecipientModel, WhatsAppBroadcastSourceContactModel):
        limits.append((select(func.count()).select_from(model).join(
            ClientGroupWhatsAppBroadcastLinkModel,
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id == model.broadcast_group_id,
        ).where(model.agency_id == agency_id,
                ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
                ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group_id), 3000))
    for statement, maximum in limits:
        if (await session.scalar(statement) or 0) > maximum:
            return False
    return True
