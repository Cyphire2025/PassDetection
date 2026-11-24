"""QR delivery receipt reduction and durable status updates."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.infrastructure.database.models import PassengerQrWhatsAppDeliveryModel
from app.infrastructure.whatsapp.qr_delivery_types import SessionFactory

ACCEPTED_STATUSES = frozenset({"submitted", "sent", "delivered", "read"})
ACCEPTED_STATUS_RANK = {"submitted": 0, "sent": 1, "delivered": 2, "read": 3}


def apply_qr_provider_status(
    delivery: PassengerQrWhatsAppDeliveryModel,
    *,
    provider_status: str,
    error_message: str | None,
    provider_status_at: datetime | None,
    now: datetime,
) -> None:
    """Apply Meta receipts monotonically so late webhooks cannot regress state."""

    if (
        delivery.provider_status_at
        and provider_status_at
        and provider_status_at < delivery.provider_status_at
    ):
        return
    if provider_status in ACCEPTED_STATUSES:
        current_rank = ACCEPTED_STATUS_RANK.get(delivery.status, -1)
        incoming_rank = ACCEPTED_STATUS_RANK[provider_status]
        if incoming_rank >= current_rank:
            delivery.status = provider_status
            delivery.status_updated_at = now
            delivery.provider_status_at = provider_status_at or delivery.provider_status_at
            delivery.updated_at = now
    elif provider_status == "failed" and delivery.status not in {"delivered", "read"}:
        delivery.status = "failed"
        delivery.status_updated_at = now
        delivery.provider_status_at = provider_status_at or delivery.provider_status_at
        delivery.updated_at = now
    if error_message:
        delivery.error_message = error_message[:2000]


async def _mark_delivery(
    delivery_id: uuid.UUID,
    *,
    session_factory: SessionFactory,
    status: str,
    error_message: str | None,
    provider_message_id: str | None = None,
    provider_media_id: str | None = None,
) -> None:
    async with session_factory() as session:
        result = await session.execute(
            select(PassengerQrWhatsAppDeliveryModel)
            .where(PassengerQrWhatsAppDeliveryModel.id == delivery_id)
            .with_for_update()
        )
        delivery = result.scalar_one_or_none()
        if not delivery:
            return
        now = datetime.now(tz=UTC)
        delivery.status = status
        delivery.status_updated_at = now
        delivery.updated_at = now
        delivery.error_message = error_message[:2000] if error_message else None
        if provider_message_id:
            delivery.provider_message_id = provider_message_id
        if provider_media_id:
            delivery.provider_media_id = provider_media_id
        await session.commit()


async def mark_qr_batch_failed(
    *, send_batch_id: str, error_message: str, session_factory: SessionFactory
) -> None:
    parsed_batch_id = uuid.UUID(send_batch_id)
    async with session_factory() as session:
        result = await session.execute(
            select(PassengerQrWhatsAppDeliveryModel).where(
                PassengerQrWhatsAppDeliveryModel.send_batch_id == parsed_batch_id,
                PassengerQrWhatsAppDeliveryModel.status.in_(["queued", "processing"]),
            )
        )
        now = datetime.now(tz=UTC)
        for delivery in result.scalars().all():
            delivery.status = "delivery_unknown" if delivery.status == "processing" else "failed"
            delivery.status_updated_at = now
            delivery.updated_at = now
            delivery.error_message = error_message[:2000]
        await session.commit()
