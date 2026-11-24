"""Authorized document-destination selection and its native status filters."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, select

from app.domain.entities.entities import User
from app.infrastructure.database.models import ClientGroupModel, DocumentWhatsAppDeliveryModel
from app.presentation.api.v1.routes.whatsapp_activity_access import _scope_client_group_statement
from app.presentation.api.v1.routes.whatsapp_activity_status import (
    SUCCESS_STATUSES,
    UNCERTAIN_STATUSES,
    _failed_status_predicate,
    _normalized_activity_status,
)
from app.presentation.api.v1.schemas.whatsapp_activity_schemas import DocumentActivityStatusFilter


def _document_activity_deliveries_statement(
    *,
    batch_id: uuid.UUID,
    current_user: User,
    stale_cutoff: datetime,
) -> Any:
    statement = (
        select(
            DocumentWhatsAppDeliveryModel.id.label("delivery_id"),
            DocumentWhatsAppDeliveryModel.passenger_name,
            DocumentWhatsAppDeliveryModel.phone_number,
            DocumentWhatsAppDeliveryModel.document_filename,
            DocumentWhatsAppDeliveryModel.document_type,
            _normalized_activity_status(
                DocumentWhatsAppDeliveryModel.status,
                DocumentWhatsAppDeliveryModel.status_updated_at,
                stale_cutoff=stale_cutoff,
            ).label("status"),
            DocumentWhatsAppDeliveryModel.error_message,
            DocumentWhatsAppDeliveryModel.status_updated_at,
        )
        .select_from(DocumentWhatsAppDeliveryModel)
        .join(
            ClientGroupModel,
            and_(
                ClientGroupModel.id == DocumentWhatsAppDeliveryModel.group_id,
                ClientGroupModel.agency_id == DocumentWhatsAppDeliveryModel.agency_id,
            ),
        )
        .where(DocumentWhatsAppDeliveryModel.send_batch_id == batch_id)
    )
    return _scope_client_group_statement(statement, current_user)


def _document_activity_status_predicate(
    status_filter: DocumentActivityStatusFilter, *, stale_cutoff: datetime,
) -> Any:
    status_column = DocumentWhatsAppDeliveryModel.status
    if status_filter == "sent":
        return status_column.in_(SUCCESS_STATUSES)
    if status_filter == "delivered":
        return status_column.in_(("delivered", "read"))
    if status_filter == "failed":
        return _failed_status_predicate(status_column)
    normalized_status = _normalized_activity_status(
        status_column,
        DocumentWhatsAppDeliveryModel.status_updated_at,
        stale_cutoff=stale_cutoff,
    )
    if status_filter == "needs_review":
        return normalized_status.in_(UNCERTAIN_STATUSES)
    return normalized_status == status_filter
