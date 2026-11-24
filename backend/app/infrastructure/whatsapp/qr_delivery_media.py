"""Reconstruct and upload only the latest active QR for a claimed delivery."""

from __future__ import annotations

import asyncio
import uuid

import httpx
from sqlalchemy import select

from app.core.config.settings import Settings
from app.infrastructure.database.models import PassengerQRTokenModel
from app.infrastructure.whatsapp.cloud_api_provider import WhatsAppCloudApiError
from app.infrastructure.whatsapp.qr_delivery_types import QrMediaCallbacks


async def prepare_qr_delivery_media(
    *,
    delivery_id: uuid.UUID,
    parsed_batch_id: uuid.UUID,
    client: httpx.AsyncClient,
    settings: Settings,
    max_attempts: int,
    callbacks: QrMediaCallbacks,
) -> str | None:
    async with callbacks.session_factory() as session:
        data_result = await session.execute(
            callbacks.source_statement(
                delivery_id=delivery_id,
                send_batch_id=parsed_batch_id,
            )
        )
        row = data_result.one_or_none()
        if not row:
            await callbacks.mark_delivery(
                delivery_id,
                status="failed",
                error_message="The saved QR code is no longer available",
            )
            return None
        delivery, token = row
        latest_result = await session.execute(
            select(PassengerQRTokenModel.id)
            .where(
                PassengerQRTokenModel.agency_id == delivery.agency_id,
                PassengerQRTokenModel.passenger_id == delivery.passenger_id,
            )
            .order_by(
                PassengerQRTokenModel.token_version.desc(),
                PassengerQRTokenModel.created_at.desc(),
            )
            .limit(1)
        )
        latest_token_id = latest_result.scalar_one_or_none()

    if (
        latest_token_id != token.id
        or callbacks.qr_status(token) != "active"
        or not token.qr_payload
    ):
        await callbacks.mark_delivery(
            delivery_id,
            status="failed",
            error_message=(
                "This QR code is no longer active; preview the current QR before sending"
            ),
        )
        return None

    try:
        image_content = await asyncio.to_thread(
            callbacks.render,
            token.qr_payload,
        )
    except ValueError:
        await callbacks.mark_delivery(
            delivery_id,
            status="failed",
            error_message=(
                "The saved QR image cannot be reconstructed; regenerate it before sending"
            ),
        )
        return None

    media_id: str | None = None
    upload_failed = False
    for attempt in range(max_attempts):
        try:
            media_id = await callbacks.upload(
                client=client,
                settings=settings,
                file_name="passenger-attendance-qr.png",
                file_content=image_content,
                content_type="image/png",
            )
            break
        except WhatsAppCloudApiError as exc:
            if exc.transient and attempt + 1 < max_attempts:
                await asyncio.sleep(2**attempt)
                continue
            await callbacks.mark_delivery(
                delivery_id,
                status="failed",
                error_message=exc.persistence_message,
            )
            upload_failed = True
            break
    if upload_failed or not media_id:
        return None

    return media_id
