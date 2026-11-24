"""Per-engine failed destinations, preserving frozen phones and display order."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    ClientGroupModel,
    DocumentWhatsAppDeliveryModel,
    PassengerQrWhatsAppDeliveryModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.presentation.api.v1.routes.whatsapp_activity_access import _scope_client_group_statement
from app.presentation.api.v1.routes.whatsapp_activity_status import _failed_status_predicate


def _broadcast_failures_statement(*, batch_id: uuid.UUID, current_user: User) -> Any:
    statement = (
        select(
            WhatsAppBroadcastRecipientModel.name.label("recipient_name"),
            func.coalesce(WhatsAppMessageLogModel.normalized_phone_number,
                          WhatsAppBroadcastRecipientModel.normalized_phone_number).label("phone_number"),
            WhatsAppMessageLogModel.error_message.label("error_message"),
        )
        .join(
            WhatsAppBroadcastRecipientModel,
            WhatsAppBroadcastRecipientModel.id == WhatsAppMessageLogModel.recipient_id,
        )
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id == WhatsAppMessageLogModel.broadcast_group_id,
        )
        .where(
            WhatsAppMessageLogModel.batch_id == batch_id,
            _failed_status_predicate(WhatsAppMessageLogModel.status),
        )
        .order_by(
            WhatsAppBroadcastRecipientModel.name.asc().nulls_last(),
            WhatsAppBroadcastRecipientModel.normalized_phone_number.asc(),
        )
    )
    if current_user.role != UserRole.SUPER_ADMIN:
        statement = statement.where(WhatsAppBroadcastGroupModel.agency_id == current_user.agency_id)
    return statement


def _document_failures_statement(*, batch_id: uuid.UUID, current_user: User) -> Any:
    statement = (
        select(
            DocumentWhatsAppDeliveryModel.passenger_name.label("recipient_name"),
            DocumentWhatsAppDeliveryModel.normalized_phone_number.label("phone_number"),
            DocumentWhatsAppDeliveryModel.error_message.label("error_message"),
        )
        .join(
            ClientGroupModel,
            ClientGroupModel.id == DocumentWhatsAppDeliveryModel.group_id,
        )
        .where(
            DocumentWhatsAppDeliveryModel.send_batch_id == batch_id,
            _failed_status_predicate(DocumentWhatsAppDeliveryModel.status),
        )
        .order_by(
            DocumentWhatsAppDeliveryModel.passenger_name.asc(),
            DocumentWhatsAppDeliveryModel.normalized_phone_number.asc(),
        )
    )
    return _scope_client_group_statement(statement, current_user)


def _qr_failures_statement(*, batch_id: uuid.UUID, current_user: User) -> Any:
    statement = (
        select(
            PassengerQrWhatsAppDeliveryModel.passenger_name.label("recipient_name"),
            PassengerQrWhatsAppDeliveryModel.normalized_phone_number.label("phone_number"),
            PassengerQrWhatsAppDeliveryModel.error_message.label("error_message"),
        )
        .join(
            ClientGroupModel,
            ClientGroupModel.id == PassengerQrWhatsAppDeliveryModel.group_id,
        )
        .where(
            PassengerQrWhatsAppDeliveryModel.send_batch_id == batch_id,
            _failed_status_predicate(PassengerQrWhatsAppDeliveryModel.status),
        )
        .order_by(
            PassengerQrWhatsAppDeliveryModel.passenger_name.asc(),
            PassengerQrWhatsAppDeliveryModel.normalized_phone_number.asc(),
        )
    )
    return _scope_client_group_statement(statement, current_user)
