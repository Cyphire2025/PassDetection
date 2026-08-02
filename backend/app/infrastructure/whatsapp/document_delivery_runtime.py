"""Worker-side execution and receipt handling for document deliveries."""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import nullcontext
from datetime import UTC, datetime

import httpx
from sqlalchemy import Select, select, update

from app.application.use_cases.whatsapp.document_templates import (
    document_template_parameters,
    legacy_document_template_parameters,
)
from app.core.config.settings import get_settings
from app.infrastructure.database.models import (
    ClientGroupModel,
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentWhatsAppDeliveryModel,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.infrastructure.whatsapp.bounded_delivery import (
    bounded_delivery_concurrency,
    run_bounded_delivery_items,
)
from app.infrastructure.whatsapp.cloud_api_provider import (
    WhatsAppCloudApiError,
    send_whatsapp_document_template,
    upload_whatsapp_document,
)
from app.infrastructure.whatsapp.private_delivery_policy import (
    PRIVATE_DELIVERY_RECIPIENT_CHANGED,
    PrivateDeliveryGroupSourceSnapshot,
    lock_private_delivery_group_source_snapshot,
    validate_private_delivery_recipient,
)

MAX_PROVIDER_ATTEMPTS = 3
ACCEPTED_STATUSES = frozenset({"submitted", "sent", "delivered", "read"})
ACCEPTED_STATUS_RANK = {"submitted": 0, "sent": 1, "delivered": 2, "read": 3}
logger = logging.getLogger(__name__)


def _document_media_source_statement(
    *,
    delivery_id: uuid.UUID,
    send_batch_id: uuid.UUID,
) -> Select[
    tuple[
        DocumentWhatsAppDeliveryModel,
        DistributedDocumentModel,
        ClientGroupModel,
    ]
]:
    return (
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
        .join(
            DocumentDistributionBatchModel,
            DocumentDistributionBatchModel.id
            == DocumentWhatsAppDeliveryModel.document_batch_id,
        )
        .where(
            DocumentWhatsAppDeliveryModel.id == delivery_id,
            DocumentWhatsAppDeliveryModel.send_batch_id == send_batch_id,
            DocumentWhatsAppDeliveryModel.status == "processing",
            DistributedDocumentModel.agency_id
            == DocumentWhatsAppDeliveryModel.agency_id,
            DistributedDocumentModel.group_id
            == DocumentWhatsAppDeliveryModel.group_id,
            DistributedDocumentModel.passenger_id
            == DocumentWhatsAppDeliveryModel.passenger_id,
            DistributedDocumentModel.batch_id
            == DocumentWhatsAppDeliveryModel.document_batch_id,
            DistributedDocumentModel.document_type
            == DocumentWhatsAppDeliveryModel.document_type,
            DistributedDocumentModel.match_status == "matched",
            DocumentDistributionBatchModel.agency_id
            == DocumentWhatsAppDeliveryModel.agency_id,
            DocumentDistributionBatchModel.group_id
            == DocumentWhatsAppDeliveryModel.group_id,
            DocumentDistributionBatchModel.document_type
            == DocumentWhatsAppDeliveryModel.document_type,
            DocumentDistributionBatchModel.status == "saved",
            ClientGroupModel.agency_id == DocumentWhatsAppDeliveryModel.agency_id,
            ClientGroupModel.deleted_at.is_(None),
        )
    )


def _locked_document_batches_statement(
    *,
    document_batch_ids: set[uuid.UUID],
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
) -> Select[tuple[uuid.UUID]]:
    return (
        select(DocumentDistributionBatchModel.id)
        .where(
            DocumentDistributionBatchModel.id.in_(sorted(document_batch_ids, key=str)),
            DocumentDistributionBatchModel.agency_id == agency_id,
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.status == "saved",
        )
        .order_by(DocumentDistributionBatchModel.id)
        .with_for_update()
    )


def _locked_document_source_statement(
    delivery: DocumentWhatsAppDeliveryModel,
    *,
    batch_fenced: bool,
) -> Select[tuple[DistributedDocumentModel, DocumentDistributionBatchModel]]:
    statement = (
        select(
            DistributedDocumentModel,
            DocumentDistributionBatchModel,
        )
        .join(
            DocumentDistributionBatchModel,
            DocumentDistributionBatchModel.id == DistributedDocumentModel.batch_id,
        )
        .where(
            DistributedDocumentModel.id == delivery.distributed_document_id,
            DistributedDocumentModel.agency_id == delivery.agency_id,
            DistributedDocumentModel.group_id == delivery.group_id,
            DistributedDocumentModel.passenger_id == delivery.passenger_id,
            DistributedDocumentModel.document_type == delivery.document_type,
            DistributedDocumentModel.match_status == "matched",
            DocumentDistributionBatchModel.id == delivery.document_batch_id,
            DocumentDistributionBatchModel.agency_id == delivery.agency_id,
            DocumentDistributionBatchModel.group_id == delivery.group_id,
            DocumentDistributionBatchModel.document_type == delivery.document_type,
            DocumentDistributionBatchModel.status == "saved",
        )
    )
    return (
        statement.with_for_update(of=DistributedDocumentModel)
        if batch_fenced
        else statement.with_for_update()
    )


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


async def run_document_whatsapp_broadcast(
    *,
    send_batch_id: str,
    _delivery_id: uuid.UUID | None = None,
    _source_snapshot: PrivateDeliveryGroupSourceSnapshot | None = None,
    _client: httpx.AsyncClient | None = None,
) -> None:
    parsed_batch_id = uuid.UUID(send_batch_id)
    settings = get_settings()
    timeout = httpx.Timeout(30.0, connect=5.0)

    if _delivery_id is None:
        async with AsyncSessionFactory() as session:
            rows_result = await session.execute(
                select(
                    DocumentWhatsAppDeliveryModel.id,
                    DocumentWhatsAppDeliveryModel.agency_id,
                    DocumentWhatsAppDeliveryModel.group_id,
                    DocumentWhatsAppDeliveryModel.document_batch_id,
                )
                .where(DocumentWhatsAppDeliveryModel.send_batch_id == parsed_batch_id)
                .order_by(DocumentWhatsAppDeliveryModel.created_at.asc())
            )
            batch_rows = list(rows_result.all())
            if not batch_rows:
                return
            source_pairs = {(row.agency_id, row.group_id) for row in batch_rows}
            if len(source_pairs) != 1:
                raise RuntimeError(
                    "A private delivery batch must belong to exactly one group"
                )
            agency_id, group_id = next(iter(source_pairs))
            source_snapshot = await lock_private_delivery_group_source_snapshot(
                session,
                agency_id=agency_id,
                group_id=group_id,
            )
            if source_snapshot is None:
                raise RuntimeError(
                    "The private delivery source is no longer available"
                )
            if any(row.document_batch_id is None for row in batch_rows):
                raise RuntimeError(
                    "A private document delivery batch has an incomplete source"
                )
            document_batch_ids = {row.document_batch_id for row in batch_rows}
            source_batch_result = await session.execute(
                _locked_document_batches_statement(
                    document_batch_ids=document_batch_ids,
                    agency_id=agency_id,
                    group_id=group_id,
                )
            )
            locked_batch_ids = set(source_batch_result.scalars().all())
            if locked_batch_ids != document_batch_ids:
                raise RuntimeError(
                    "One or more private document sources are no longer saved"
                )
            concurrency = bounded_delivery_concurrency(
                getattr(settings, "whatsapp_delivery_concurrency", 4)
            )
            async with httpx.AsyncClient(timeout=timeout) as client:
                await run_bounded_delivery_items(
                    [row.id for row in batch_rows],
                    lambda delivery_id: run_document_whatsapp_broadcast(
                        send_batch_id=send_batch_id,
                        _delivery_id=delivery_id,
                        _source_snapshot=source_snapshot,
                        _client=client,
                    ),
                    concurrency=concurrency,
                )
        return

    delivery_ids = [_delivery_id]

    storage = MinioStorageRepository()
    client_context = (
        nullcontext(_client)
        if _client is not None
        else httpx.AsyncClient(timeout=timeout)
    )
    async with client_context as client:
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
                    _document_media_source_statement(
                        delivery_id=delivery_id,
                        send_batch_id=parsed_batch_id,
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

            # The batch coordinator retains one authoritative identity-source
            # fence. Lock only this item's document/batch and delivery rows here
            # so distinct provider requests can overlap without weakening the
            # recipient snapshot.
            async with AsyncSessionFactory() as session:
                snapshot_result = await session.execute(
                    select(DocumentWhatsAppDeliveryModel)
                    .where(
                        DocumentWhatsAppDeliveryModel.id == delivery_id,
                        DocumentWhatsAppDeliveryModel.send_batch_id == parsed_batch_id,
                        DocumentWhatsAppDeliveryModel.status == "processing",
                    )
                )
                delivery_snapshot = snapshot_result.scalar_one_or_none()
                if not delivery_snapshot:
                    continue
                queued_identity = (
                    delivery_snapshot.agency_id,
                    delivery_snapshot.group_id,
                    delivery_snapshot.passenger_id,
                    delivery_snapshot.distributed_document_id,
                    delivery_snapshot.document_batch_id,
                    delivery_snapshot.broadcast_group_id,
                    delivery_snapshot.recipient_id,
                    delivery_snapshot.normalized_phone_number,
                )

                validation = (
                    None
                    if _source_snapshot is not None
                    else await validate_private_delivery_recipient(
                        session,
                        agency_id=delivery_snapshot.agency_id,
                        group_id=delivery_snapshot.group_id,
                        passenger_id=delivery_snapshot.passenger_id,
                        broadcast_group_id=delivery_snapshot.broadcast_group_id,
                        recipient_id=delivery_snapshot.recipient_id,
                        normalized_phone_number=(
                            delivery_snapshot.normalized_phone_number
                        ),
                    )
                )
                recipient_allowed = (
                    _source_snapshot.allows(
                        agency_id=delivery_snapshot.agency_id,
                        group_id=delivery_snapshot.group_id,
                        passenger_id=delivery_snapshot.passenger_id,
                        broadcast_group_id=delivery_snapshot.broadcast_group_id,
                        recipient_id=delivery_snapshot.recipient_id,
                        normalized_phone_number=(
                            delivery_snapshot.normalized_phone_number
                        ),
                    )
                    if _source_snapshot is not None
                    else bool(validation and validation.allowed)
                )

                source_result = await session.execute(
                    _locked_document_source_statement(
                        delivery_snapshot,
                        batch_fenced=_source_snapshot is not None,
                    )
                )
                source_row = source_result.one_or_none()
                locked_result = await session.execute(
                    select(DocumentWhatsAppDeliveryModel)
                    .where(
                        DocumentWhatsAppDeliveryModel.id == delivery_id,
                        DocumentWhatsAppDeliveryModel.send_batch_id == parsed_batch_id,
                        DocumentWhatsAppDeliveryModel.status == "processing",
                    )
                    .with_for_update()
                )
                locked_delivery = locked_result.scalar_one_or_none()
                current_identity = (
                    (
                        locked_delivery.agency_id,
                        locked_delivery.group_id,
                        locked_delivery.passenger_id,
                        locked_delivery.distributed_document_id,
                        locked_delivery.document_batch_id,
                        locked_delivery.broadcast_group_id,
                        locked_delivery.recipient_id,
                        locked_delivery.normalized_phone_number,
                    )
                    if locked_delivery
                    else None
                )
                if not locked_delivery:
                    continue
                if (
                    source_row is None
                    or not recipient_allowed
                    or current_identity != queued_identity
                ):
                    now = datetime.now(tz=UTC)
                    locked_delivery.status = "failed"
                    locked_delivery.status_updated_at = now
                    locked_delivery.updated_at = now
                    locked_delivery.provider_media_id = media_id
                    locked_delivery.error_message = (
                        validation.reason
                        if validation is not None and not validation.allowed
                        else PRIVATE_DELIVERY_RECIPIENT_CHANGED
                    )
                    await session.commit()
                    continue

                _source_document, _source_batch = source_row
                saved_parameters = locked_delivery.template_parameter_values
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
                        passenger_name=locked_delivery.passenger_name,
                        document_type=locked_delivery.document_type,
                        group_name=(
                            _source_snapshot.group_name
                            if _source_snapshot is not None
                            else group.name
                        ),
                    )
                )
                for attempt in range(MAX_PROVIDER_ATTEMPTS):
                    try:
                        provider_id = await send_whatsapp_document_template(
                            client=client,
                            settings=settings,
                            to_number=locked_delivery.normalized_phone_number,
                            template_name=locked_delivery.template_name,
                            media_id=media_id,
                            filename=locked_delivery.document_filename,
                            parameters=parameters,
                        )
                    except WhatsAppCloudApiError as exc:
                        if exc.delivery_unknown:
                            locked_delivery.status = "delivery_unknown"
                            locked_delivery.error_message = exc.persistence_message
                            break
                        if exc.transient and attempt + 1 < MAX_PROVIDER_ATTEMPTS:
                            await asyncio.sleep(2**attempt)
                            continue
                        locked_delivery.status = "failed"
                        locked_delivery.error_message = exc.persistence_message
                        break
                    except Exception:  # noqa: BLE001 - outcome is ambiguous.
                        logger.warning(
                            "document_whatsapp_provider_outcome_unknown delivery_id=%s",
                            delivery_id,
                        )
                        locked_delivery.status = "delivery_unknown"
                        locked_delivery.error_message = (
                            "WhatsApp delivery outcome is unknown; automatic resend "
                            "is suppressed"
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
                await session.commit()


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
