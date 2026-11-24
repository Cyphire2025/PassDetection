"""Fence the current QR and recipient before sending and binding its receipt."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from app.application.use_cases.whatsapp.qr_templates import (
    QR_DEFAULT_MESSAGE_CONTENT,
    qr_template_parameters,
)
from app.core.config.settings import Settings
from app.infrastructure.database.models import (
    PassengerQRTokenModel,
    PassengerQrWhatsAppDeliveryModel,
)
from app.infrastructure.whatsapp.cloud_api_provider import WhatsAppCloudApiError
from app.infrastructure.whatsapp.private_delivery_policy import (
    PRIVATE_DELIVERY_RECIPIENT_CHANGED,
    PrivateDeliveryGroupSourceSnapshot,
)
from app.infrastructure.whatsapp.qr_delivery_types import QrDispatchCallbacks

logger = logging.getLogger("app.infrastructure.whatsapp.qr_delivery_runtime")


async def dispatch_qr_delivery(
    *,
    delivery_id: uuid.UUID,
    parsed_batch_id: uuid.UUID,
    client: httpx.AsyncClient,
    settings: Settings,
    media_id: str,
    source_snapshot: PrivateDeliveryGroupSourceSnapshot | None,
    max_attempts: int,
    callbacks: QrDispatchCallbacks,
) -> None:
    # The batch coordinator retains one authoritative identity-source
    # fence. Lock only this item's QR token and delivery row here so
    # distinct provider requests can overlap safely.
    async with callbacks.session_factory() as session:
        snapshot_result = await session.execute(
            select(PassengerQrWhatsAppDeliveryModel).where(
                PassengerQrWhatsAppDeliveryModel.id == delivery_id,
                PassengerQrWhatsAppDeliveryModel.send_batch_id == parsed_batch_id,
                PassengerQrWhatsAppDeliveryModel.status == "processing",
            )
        )
        delivery_snapshot = snapshot_result.scalar_one_or_none()
        if not delivery_snapshot:
            return
        queued_identity = (
            delivery_snapshot.agency_id,
            delivery_snapshot.group_id,
            delivery_snapshot.passenger_id,
            delivery_snapshot.qr_token_id,
            delivery_snapshot.broadcast_group_id,
            delivery_snapshot.recipient_id,
            delivery_snapshot.normalized_phone_number,
        )

        validation = (
            None
            if source_snapshot is not None
            else await callbacks.validate_recipient(
                session,
                agency_id=delivery_snapshot.agency_id,
                group_id=delivery_snapshot.group_id,
                passenger_id=delivery_snapshot.passenger_id,
                broadcast_group_id=delivery_snapshot.broadcast_group_id,
                recipient_id=delivery_snapshot.recipient_id,
                normalized_phone_number=(delivery_snapshot.normalized_phone_number),
            )
        )
        recipient_allowed = (
            source_snapshot.allows(
                agency_id=delivery_snapshot.agency_id,
                group_id=delivery_snapshot.group_id,
                passenger_id=delivery_snapshot.passenger_id,
                broadcast_group_id=delivery_snapshot.broadcast_group_id,
                recipient_id=delivery_snapshot.recipient_id,
                normalized_phone_number=(delivery_snapshot.normalized_phone_number),
            )
            if source_snapshot is not None
            else bool(validation and validation.allowed)
        )
        if recipient_allowed and source_snapshot is not None:
            validation = await callbacks.validate_welcome(
                session,
                agency_id=delivery_snapshot.agency_id,
                normalized_phone_number=delivery_snapshot.normalized_phone_number,
            )
            recipient_allowed = validation.allowed

        token_result = await session.execute(
            select(PassengerQRTokenModel)
            .where(
                PassengerQRTokenModel.id == delivery_snapshot.qr_token_id,
                PassengerQRTokenModel.agency_id == delivery_snapshot.agency_id,
                PassengerQRTokenModel.passenger_id == delivery_snapshot.passenger_id,
            )
            .with_for_update()
        )
        current_token = token_result.scalar_one_or_none()
        latest_result = await session.execute(
            select(PassengerQRTokenModel.id)
            .where(
                PassengerQRTokenModel.agency_id == delivery_snapshot.agency_id,
                PassengerQRTokenModel.passenger_id == delivery_snapshot.passenger_id,
            )
            .order_by(
                PassengerQRTokenModel.token_version.desc(),
                PassengerQRTokenModel.created_at.desc(),
            )
            .limit(1)
        )
        latest_token_id = latest_result.scalar_one_or_none()
        locked_result = await session.execute(
            select(PassengerQrWhatsAppDeliveryModel)
            .where(
                PassengerQrWhatsAppDeliveryModel.id == delivery_id,
                PassengerQrWhatsAppDeliveryModel.send_batch_id == parsed_batch_id,
                PassengerQrWhatsAppDeliveryModel.status == "processing",
            )
            .with_for_update()
        )
        locked_delivery = locked_result.scalar_one_or_none()
        current_identity = (
            (
                locked_delivery.agency_id,
                locked_delivery.group_id,
                locked_delivery.passenger_id,
                locked_delivery.qr_token_id,
                locked_delivery.broadcast_group_id,
                locked_delivery.recipient_id,
                locked_delivery.normalized_phone_number,
            )
            if locked_delivery
            else None
        )
        if not locked_delivery:
            return
        token_is_current = bool(
            current_token
            and latest_token_id == current_token.id
            and callbacks.qr_status(current_token) == "active"
            and current_token.qr_payload
        )
        if not token_is_current or not recipient_allowed or current_identity != queued_identity:
            now = datetime.now(tz=UTC)
            locked_delivery.status = "failed"
            locked_delivery.status_updated_at = now
            locked_delivery.updated_at = now
            locked_delivery.provider_media_id = media_id
            locked_delivery.error_message = (
                (validation.reason or PRIVATE_DELIVERY_RECIPIENT_CHANGED)
                if validation is not None and not validation.allowed
                else PRIVATE_DELIVERY_RECIPIENT_CHANGED
                if not recipient_allowed
                else ("This QR code changed after queueing; preview the current QR before sending")
            )
            await session.commit()
            return

        saved_parameters = locked_delivery.template_parameter_values
        parameters = (
            qr_template_parameters(message_content=saved_parameters[0])
            if (
                isinstance(saved_parameters, list)
                and len(saved_parameters) == 1
                and isinstance(saved_parameters[0], str)
            )
            else qr_template_parameters(message_content=QR_DEFAULT_MESSAGE_CONTENT)
        )
        for attempt in range(max_attempts):
            try:
                provider_id = await callbacks.send_template(
                    client=client,
                    settings=settings,
                    to_number=locked_delivery.normalized_phone_number,
                    template_name=locked_delivery.template_name,
                    media_id=media_id,
                    parameters=parameters,
                )
            except WhatsAppCloudApiError as exc:
                if exc.delivery_unknown:
                    locked_delivery.status = "delivery_unknown"
                    locked_delivery.error_message = exc.persistence_message
                    break
                if exc.transient and attempt + 1 < max_attempts:
                    await asyncio.sleep(2**attempt)
                    continue
                locked_delivery.status = "failed"
                locked_delivery.error_message = exc.persistence_message
                break
            except Exception:  # noqa: BLE001 - provider outcome is ambiguous.
                logger.warning(
                    "qr_whatsapp_provider_outcome_unknown delivery_id=%s",
                    delivery_id,
                )
                locked_delivery.status = "delivery_unknown"
                locked_delivery.error_message = (
                    "WhatsApp delivery outcome is unknown; automatic resend is suppressed"
                )
                break
            else:
                locked_delivery.status = "submitted"
                locked_delivery.error_message = None
                locked_delivery.provider_message_id = provider_id
                break
        now = datetime.now(tz=UTC)
        locked_delivery.provider_media_id = media_id
        locked_delivery.status_updated_at = now
        locked_delivery.updated_at = now
        await callbacks.commit_outcome(
            session,
            locked_delivery,
            provider_phone_number_id=settings.whatsapp_phone_number_id,
        )
