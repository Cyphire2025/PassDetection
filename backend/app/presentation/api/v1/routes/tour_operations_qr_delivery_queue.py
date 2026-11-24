"""Persist one QR-version admission and publish only after its durable commit."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import (
    User,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassengerQrWhatsAppDeliveryModel,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    QrDeliveryPreviewRecipient,
)


async def queue_qr_deliveries(
    session: AsyncSession,
    *,
    group: ClientGroupModel,
    current_user: User,
    eligible_rows: list[QrDeliveryPreviewRecipient],
    send_batch_id: uuid.UUID,
    now: datetime,
    template_name: str,
    message_content: str,
) -> int:
    queued_count = 0
    for row in eligible_rows:
        if not (
            row.qr_token_id and row.recipient_id and row.broadcast_group_id and row.phone_number
        ):
            continue
        delivery: PassengerQrWhatsAppDeliveryModel | None = None
        if row.delivery_id:
            delivery_result = await session.execute(
                select(PassengerQrWhatsAppDeliveryModel)
                .where(PassengerQrWhatsAppDeliveryModel.id == row.delivery_id)
                .with_for_update()
            )
            delivery = delivery_result.scalar_one_or_none()
        if delivery:
            if delivery.status != "failed":
                continue
            delivery.send_batch_id = send_batch_id
            delivery.broadcast_group_id = row.broadcast_group_id
            delivery.recipient_id = row.recipient_id
            delivery.phone_number = row.phone_number
            delivery.normalized_phone_number = row.phone_number
            delivery.template_name = template_name
            delivery.template_parameter_values = [message_content]
            delivery.status = "queued"
            delivery.status_updated_at = now
            delivery.provider_status_at = None
            delivery.provider_message_id = None
            delivery.provider_media_id = None
            delivery.error_message = None
            delivery.updated_at = now
        else:
            delivery = PassengerQrWhatsAppDeliveryModel(
                id=uuid.uuid4(),
                agency_id=group.agency_id,
                group_id=group.id,
                passenger_id=row.passenger_id,
                qr_token_id=row.qr_token_id,
                broadcast_group_id=row.broadcast_group_id,
                recipient_id=row.recipient_id,
                send_batch_id=send_batch_id,
                passenger_name=row.passenger_name,
                passport_number=row.passport_number,
                phone_number=row.phone_number,
                normalized_phone_number=row.phone_number,
                template_name=template_name,
                template_parameter_values=[message_content],
                status="queued",
                attempt_count=0,
                status_updated_at=now,
                created_by_user_id=current_user.id,
                created_at=now,
                updated_at=now,
            )
            session.add(delivery)
        queued_count += 1
    if not queued_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The selected QR codes were already claimed by another send",
        )
    return queued_count


async def publish_qr_delivery_batch(session: AsyncSession, *, send_batch_id: uuid.UUID) -> None:
    from app.infrastructure.whatsapp.tasks import process_qr_whatsapp_broadcast

    try:
        process_qr_whatsapp_broadcast.apply_async(
            kwargs={"send_batch_id": str(send_batch_id)}, queue="whatsapp"
        )
    except Exception as exc:
        failed_result = await session.execute(
            select(PassengerQrWhatsAppDeliveryModel).where(
                PassengerQrWhatsAppDeliveryModel.send_batch_id == send_batch_id,
                PassengerQrWhatsAppDeliveryModel.status == "queued",
            )
        )
        failure_time = datetime.now(tz=UTC)
        for delivery in failed_result.scalars().all():
            delivery.status = "failed"
            delivery.status_updated_at = failure_time
            delivery.updated_at = failure_time
            delivery.error_message = "The WhatsApp worker queue is temporarily unavailable"
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The WhatsApp worker queue is temporarily unavailable",
        ) from exc
