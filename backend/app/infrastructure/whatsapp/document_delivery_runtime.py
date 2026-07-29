"""Worker-side execution and receipt handling for document deliveries."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import select, update

from app.application.use_cases.whatsapp.document_templates import (
    document_template_parameters,
    legacy_document_template_parameters,
)
from app.core.config.settings import get_settings
from app.infrastructure.database.models import (
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentWhatsAppDeliveryModel,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.infrastructure.whatsapp.cloud_api_provider import (
    WhatsAppCloudApiError,
    send_whatsapp_document_template,
    upload_whatsapp_document,
)

MAX_PROVIDER_ATTEMPTS = 3
ACCEPTED_STATUSES = frozenset({"submitted", "sent", "delivered", "read"})
ACCEPTED_STATUS_RANK = {"submitted": 0, "sent": 1, "delivered": 2, "read": 3}
logger = logging.getLogger(__name__)


def apply_document_provider_status(
    delivery: DocumentWhatsAppDeliveryModel,
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
            delivery.provider_status_at = (
                provider_status_at or delivery.provider_status_at
            )
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
    status: str,
    error_message: str | None,
    provider_message_id: str | None = None,
    provider_media_id: str | None = None,
) -> None:
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(DocumentWhatsAppDeliveryModel)
            .where(DocumentWhatsAppDeliveryModel.id == delivery_id)
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


async def run_document_whatsapp_broadcast(*, send_batch_id: str) -> None:
    parsed_batch_id = uuid.UUID(send_batch_id)
    settings = get_settings()
    timeout = httpx.Timeout(30.0, connect=5.0)

    async with AsyncSessionFactory() as session:
        rows_result = await session.execute(
            select(DocumentWhatsAppDeliveryModel.id)
            .where(DocumentWhatsAppDeliveryModel.send_batch_id == parsed_batch_id)
            .order_by(DocumentWhatsAppDeliveryModel.created_at.asc())
        )
        delivery_ids = list(rows_result.scalars().all())

    storage = MinioStorageRepository()
    async with httpx.AsyncClient(timeout=timeout) as client:
        for delivery_id in delivery_ids:
            async with AsyncSessionFactory() as session:
                claim_time = datetime.now(tz=UTC)
                claim_result = await session.execute(
                    update(DocumentWhatsAppDeliveryModel)
                    .where(
                        DocumentWhatsAppDeliveryModel.id == delivery_id,
                        DocumentWhatsAppDeliveryModel.send_batch_id == parsed_batch_id,
                        DocumentWhatsAppDeliveryModel.status == "queued",
                    )
                    .values(
                        status="processing",
                        status_updated_at=claim_time,
                        updated_at=claim_time,
                        attempt_count=DocumentWhatsAppDeliveryModel.attempt_count + 1,
                    )
                    .returning(DocumentWhatsAppDeliveryModel.id)
                    .execution_options(synchronize_session=False)
                )
                claimed_id = claim_result.scalar_one_or_none()
                if not claimed_id:
                    await session.rollback()
                    stale_result = await session.execute(
                        select(DocumentWhatsAppDeliveryModel)
                        .where(
                            DocumentWhatsAppDeliveryModel.id == delivery_id,
                            DocumentWhatsAppDeliveryModel.send_batch_id == parsed_batch_id,
                            DocumentWhatsAppDeliveryModel.status == "processing",
                        )
                        .with_for_update()
                    )
                    stale = stale_result.scalar_one_or_none()
                    if stale:
                        stale.status = "delivery_unknown"
                        stale.status_updated_at = claim_time
                        stale.updated_at = claim_time
                        stale.error_message = (
                            "A retried worker found an interrupted provider request; "
                            "automatic resend is suppressed"
                        )
                        await session.commit()
                    continue
                await session.commit()

            async with AsyncSessionFactory() as session:
                data_result = await session.execute(
                    select(
                        DocumentWhatsAppDeliveryModel,
                        DistributedDocumentModel,
                        ClientGroupModel,
                    )
                    .join(
                        DistributedDocumentModel,
                        DistributedDocumentModel.id
                        == DocumentWhatsAppDeliveryModel.distributed_document_id,
                    )
                    .join(
                        ClientGroupModel,
                        ClientGroupModel.id == DocumentWhatsAppDeliveryModel.group_id,
                    )
                    .where(
                        DocumentWhatsAppDeliveryModel.id == delivery_id,
                        DocumentWhatsAppDeliveryModel.send_batch_id == parsed_batch_id,
                        DocumentWhatsAppDeliveryModel.status == "processing",
                    )
                )
                row = data_result.one_or_none()
                if not row:
                    await _mark_delivery(
                        delivery_id,
                        status="failed",
                        error_message="The saved document is no longer available",
                    )
                    continue
                delivery, document, group = row

            try:
                content = await storage.get_file(document.storage_key)
            except Exception:  # noqa: BLE001 - details belong in server logs only.
                logger.warning(
                    "document_whatsapp_storage_read_failed delivery_id=%s",
                    delivery_id,
                )
                await _mark_delivery(
                    delivery_id,
                    status="failed",
                    error_message="The saved document could not be read from storage",
                )
                continue

            media_id: str | None = None
            upload_failed = False
            for attempt in range(MAX_PROVIDER_ATTEMPTS):
                try:
                    media_id = await upload_whatsapp_document(
                        client=client,
                        settings=settings,
                        file_name=delivery.document_filename,
                        file_content=content,
                        content_type=document.content_type,
                    )
                    break
                except WhatsAppCloudApiError as exc:
                    if exc.transient and attempt + 1 < MAX_PROVIDER_ATTEMPTS:
                        await asyncio.sleep(2**attempt)
                        continue
                    await _mark_delivery(
                        delivery_id,
                        status="failed",
                        error_message=exc.persistence_message,
                    )
                    upload_failed = True
                    break
            if upload_failed or not media_id:
                continue

            saved_parameters = delivery.template_parameter_values
            parameters = (
                document_template_parameters(
                    message_content_1=saved_parameters[0],
                    message_content_2=saved_parameters[1],
                )
                if (
                    isinstance(saved_parameters, list)
                    and len(saved_parameters) == 2
                    and all(isinstance(value, str) for value in saved_parameters)
                )
                else legacy_document_template_parameters(
                    passenger_name=delivery.passenger_name,
                    document_type=delivery.document_type,
                    group_name=group.name,
                )
            )
            for attempt in range(MAX_PROVIDER_ATTEMPTS):
                try:
                    provider_id = await send_whatsapp_document_template(
                        client=client,
                        settings=settings,
                        to_number=delivery.normalized_phone_number,
                        template_name=delivery.template_name,
                        media_id=media_id,
                        filename=delivery.document_filename,
                        parameters=parameters,
                    )
                except WhatsAppCloudApiError as exc:
                    if exc.delivery_unknown:
                        await _mark_delivery(
                            delivery_id,
                            status="delivery_unknown",
                            error_message=exc.persistence_message,
                            provider_media_id=media_id,
                        )
                        break
                    if exc.transient and attempt + 1 < MAX_PROVIDER_ATTEMPTS:
                        await asyncio.sleep(2**attempt)
                        continue
                    await _mark_delivery(
                        delivery_id,
                        status="failed",
                        error_message=exc.persistence_message,
                        provider_media_id=media_id,
                    )
                    break
                except Exception:  # noqa: BLE001 - outcome is ambiguous.
                    logger.warning(
                        "document_whatsapp_provider_outcome_unknown delivery_id=%s",
                        delivery_id,
                    )
                    await _mark_delivery(
                        delivery_id,
                        status="delivery_unknown",
                        error_message=(
                            "WhatsApp delivery outcome is unknown; automatic resend "
                            "is suppressed"
                        ),
                        provider_media_id=media_id,
                    )
                    break
                else:
                    await _mark_delivery(
                        delivery_id,
                        status="submitted",
                        error_message=None,
                        provider_message_id=provider_id,
                        provider_media_id=media_id,
                    )
                    break


async def mark_document_batch_failed(*, send_batch_id: str, error_message: str) -> None:
    parsed_batch_id = uuid.UUID(send_batch_id)
    async with AsyncSessionFactory() as session:
        result = await session.execute(
            select(DocumentWhatsAppDeliveryModel).where(
                DocumentWhatsAppDeliveryModel.send_batch_id == parsed_batch_id,
                DocumentWhatsAppDeliveryModel.status.in_(["queued", "processing"]),
            )
        )
        now = datetime.now(tz=UTC)
        for delivery in result.scalars().all():
            delivery.status = (
                "delivery_unknown" if delivery.status == "processing" else "failed"
            )
            delivery.status_updated_at = now
            delivery.updated_at = now
            delivery.error_message = error_message[:2000]
        await session.commit()
