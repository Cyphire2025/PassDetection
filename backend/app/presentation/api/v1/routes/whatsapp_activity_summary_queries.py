"""Per-engine aggregate queries for authorized, resumable activity summaries."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, select

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    ClientGroupModel,
    DocumentWhatsAppDeliveryModel,
    PassengerQrWhatsAppDeliveryModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppMessageLogModel,
)
from app.presentation.api.v1.routes.whatsapp_activity_access import _scope_client_group_statement
from app.presentation.api.v1.routes.whatsapp_activity_status import _status_aggregates


def _broadcast_activity_statement(
    *,
    batch_id: uuid.UUID,
    current_user: User,
    stale_cutoff: datetime,
) -> Any:
    statement = (
        select(
            WhatsAppMessageLogModel.batch_id.label("activity_id"),
            WhatsAppBroadcastGroupModel.id.label("source_group_id"),
            WhatsAppBroadcastGroupModel.name.label("context_label"),
            WhatsAppMessageLogModel.message_type.label("activity_label"),
            *_status_aggregates(
                WhatsAppMessageLogModel.status,
                WhatsAppMessageLogModel.status_updated_at,
                stale_cutoff=stale_cutoff,
            ),
            func.min(WhatsAppMessageLogModel.created_at).label("started_at"),
            func.max(WhatsAppMessageLogModel.status_updated_at).label("updated_at"),
        )
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id == WhatsAppMessageLogModel.broadcast_group_id,
        )
        .where(WhatsAppMessageLogModel.batch_id == batch_id)
        .group_by(
            WhatsAppMessageLogModel.batch_id,
            WhatsAppBroadcastGroupModel.id,
            WhatsAppBroadcastGroupModel.name,
            WhatsAppMessageLogModel.message_type,
        )
    )
    if current_user.role != UserRole.SUPER_ADMIN:
        statement = statement.where(WhatsAppBroadcastGroupModel.agency_id == current_user.agency_id)
    return statement


def _document_activity_statement(
    *,
    batch_id: uuid.UUID,
    current_user: User,
    stale_cutoff: datetime,
) -> Any:
    statement = (
        select(
            DocumentWhatsAppDeliveryModel.send_batch_id.label("activity_id"),
            ClientGroupModel.id.label("source_group_id"),
            ClientGroupModel.name.label("context_label"),
            DocumentWhatsAppDeliveryModel.document_type.label("activity_label"),
            *_status_aggregates(
                DocumentWhatsAppDeliveryModel.status,
                DocumentWhatsAppDeliveryModel.status_updated_at,
                stale_cutoff=stale_cutoff,
            ),
            func.min(DocumentWhatsAppDeliveryModel.created_at).label("started_at"),
            func.max(DocumentWhatsAppDeliveryModel.status_updated_at).label("updated_at"),
        )
        .join(
            ClientGroupModel,
            and_(
                ClientGroupModel.id == DocumentWhatsAppDeliveryModel.group_id,
                ClientGroupModel.agency_id == DocumentWhatsAppDeliveryModel.agency_id,
            ),
        )
        .where(DocumentWhatsAppDeliveryModel.send_batch_id == batch_id)
        .group_by(
            DocumentWhatsAppDeliveryModel.send_batch_id,
            ClientGroupModel.id,
            ClientGroupModel.name,
            DocumentWhatsAppDeliveryModel.document_type,
        )
    )
    return _scope_client_group_statement(statement, current_user)


def _qr_activity_statement(
    *,
    batch_id: uuid.UUID,
    current_user: User,
    stale_cutoff: datetime,
) -> Any:
    statement = (
        select(
            PassengerQrWhatsAppDeliveryModel.send_batch_id.label("activity_id"),
            ClientGroupModel.id.label("source_group_id"),
            ClientGroupModel.name.label("context_label"),
            *_status_aggregates(
                PassengerQrWhatsAppDeliveryModel.status,
                PassengerQrWhatsAppDeliveryModel.status_updated_at,
                stale_cutoff=stale_cutoff,
            ),
            func.min(PassengerQrWhatsAppDeliveryModel.created_at).label("started_at"),
            func.max(PassengerQrWhatsAppDeliveryModel.status_updated_at).label("updated_at"),
        )
        .join(
            ClientGroupModel,
            ClientGroupModel.id == PassengerQrWhatsAppDeliveryModel.group_id,
        )
        .where(PassengerQrWhatsAppDeliveryModel.send_batch_id == batch_id)
        .group_by(
            PassengerQrWhatsAppDeliveryModel.send_batch_id,
            ClientGroupModel.id,
            ClientGroupModel.name,
        )
    )
    return _scope_client_group_statement(statement, current_user)
