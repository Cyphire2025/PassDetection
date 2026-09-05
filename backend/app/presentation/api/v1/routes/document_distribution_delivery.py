"""Document distribution: delivery."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.domain.value_objects.travel_document_taxonomy import DOCUMENT_TYPES
from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentWhatsAppDeliveryModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.whatsapp.publication import (
    publish_whatsapp_task,
)
from app.presentation.api.v1.routes.document_distribution_delivery_preview import (
    _build_document_delivery_preview,
)
from app.presentation.api.v1.routes.document_distribution_queries import _latest_document_batch
from app.presentation.api.v1.routes.document_distribution_scope import (
    _get_authorized_group,
    _get_visible_document_batch,
    _group_passengers,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    _document_delivery_poll_after_seconds,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DocumentDeliveryPreviewResponse,
    DocumentDeliveryTrackingCounts,
    DocumentDeliveryTrackingResponse,
    DocumentDeliveryTrackingRow,
    SendDocumentBroadcastRequest,
    SendDocumentBroadcastResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.get(
    "/groups/{group_id}/{document_type}/whatsapp-preview",
    response_model=DocumentDeliveryPreviewResponse,
)
async def preview_document_whatsapp_broadcast(
    group_id: uuid.UUID,
    document_type: str,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentDeliveryPreviewResponse:
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported document type",
        )
    group = await _get_authorized_group(
        group_id,
        current_user=current_user,
        session=session,
    )
    batch = await _latest_document_batch(
        session,
        group_id=group_id,
        agency_id=group.agency_id,
        document_type=document_type,
    )
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document batch was not found",
        )
    passengers = await _group_passengers(
        group_id,
        current_user=current_user,
        session=session,
    )
    return await _build_document_delivery_preview(
        session,
        group=group,
        batch=batch,
        passengers=passengers,
    )


async def _lock_retry_document_deliveries(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    delivery_document_ids: dict[uuid.UUID, uuid.UUID],
) -> dict[uuid.UUID, DocumentWhatsAppDeliveryModel]:
    """Batch-lock retry rows and retain only exact tenant/document ownership."""

    if not delivery_document_ids:
        return {}
    result = await session.execute(
        select(DocumentWhatsAppDeliveryModel)
        .where(
            DocumentWhatsAppDeliveryModel.id.in_(list(delivery_document_ids)),
            DocumentWhatsAppDeliveryModel.agency_id == agency_id,
            DocumentWhatsAppDeliveryModel.group_id == group_id,
            DocumentWhatsAppDeliveryModel.distributed_document_id.in_(
                list(set(delivery_document_ids.values()))
            ),
        )
        .order_by(DocumentWhatsAppDeliveryModel.id)
        .with_for_update()
    )
    return {
        delivery.id: delivery
        for delivery in result.scalars().all()
        if delivery.distributed_document_id == delivery_document_ids.get(delivery.id)
    }


@router.post(
    "/batches/{batch_id}/whatsapp-send",
    response_model=SendDocumentBroadcastResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_cookie_csrf)],
)
async def send_document_whatsapp_broadcast(
    batch_id: uuid.UUID,
    payload: SendDocumentBroadcastRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> SendDocumentBroadcastResponse:
    message_content_1 = payload.message_content_1.strip()
    message_content_2 = payload.message_content_2.strip()
    if not message_content_1 or not message_content_2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both editable document message sections are required",
        )
    batch = await _get_visible_document_batch(
        session,
        batch_id=batch_id,
        current_user=current_user,
    )
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document batch was not found",
        )
    group = await _get_authorized_group(
        batch.group_id,
        current_user=current_user,
        session=session,
    )
    # Serialize the whole group/type ledger, not just the caller's possibly
    # stale batch id. This closes the race where two clients could otherwise
    # create concurrent first-send or explicit-resend attempts.
    await session.execute(
        select(DocumentDistributionBatchModel.id)
        .where(
            DocumentDistributionBatchModel.group_id == batch.group_id,
            DocumentDistributionBatchModel.agency_id == batch.agency_id,
            DocumentDistributionBatchModel.document_type == batch.document_type,
        )
        .order_by(DocumentDistributionBatchModel.id)
        .with_for_update()
    )
    passengers = await _group_passengers(
        batch.group_id,
        current_user=current_user,
        session=session,
    )
    preview = await _build_document_delivery_preview(
        session,
        group=group,
        batch=batch,
        passengers=passengers,
    )
    if not preview.can_send:
        error_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if not preview.template_configured
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(
            status_code=error_status,
            detail=preview.configuration_error or "Documents are not ready to send",
        )

    requested_ids = (
        set(payload.document_ids)
        if payload.document_ids is not None
        else {row.document_id for row in preview.recipients if row.document_id and row.eligible}
    )
    resend_ids = set(payload.resend_document_ids)
    if not resend_ids.issubset(requested_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Every resend document must also be selected for sending",
        )
    resendable_ids = {
        row.document_id for row in preview.recipients if row.document_id and row.resend_allowed
    }
    invalid_resend_ids = resend_ids - resendable_ids
    if invalid_resend_ids:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=("A selected resend is not eligible. Refresh the preview before trying again."),
        )
    eligible_rows = [
        row
        for row in preview.recipients
        if row.document_id in requested_ids and (row.eligible or row.document_id in resend_ids)
    ]
    if not eligible_rows:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Select at least one new or safely retryable document",
        )

    send_batch_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    template_name = preview.template_name or ""
    selected_document_result = await session.execute(
        select(DistributedDocumentModel).where(
            DistributedDocumentModel.id.in_(
                [row.document_id for row in eligible_rows if row.document_id]
            ),
            DistributedDocumentModel.group_id == batch.group_id,
            DistributedDocumentModel.agency_id == batch.agency_id,
        )
    )
    selected_documents = {
        document.id: document for document in selected_document_result.scalars().all()
    }
    retry_delivery_document_ids = {
        row.delivery_id: row.document_id
        for row in eligible_rows
        if row.delivery_id and row.document_id and row.document_id not in resend_ids
    }
    locked_retry_deliveries = await _lock_retry_document_deliveries(
        session,
        agency_id=batch.agency_id,
        group_id=batch.group_id,
        delivery_document_ids=retry_delivery_document_ids,
    )
    queued_count = 0
    for row in eligible_rows:
        if not (
            row.document_id
            and row.recipient_id
            and row.broadcast_group_id
            and row.phone_number
            and row.document_filename
        ):
            continue
        document = selected_documents.get(row.document_id)
        if document is None:
            continue
        explicit_resend = row.document_id in resend_ids
        delivery: DocumentWhatsAppDeliveryModel | None = None
        if row.delivery_id and not explicit_resend:
            delivery = locked_retry_deliveries.get(row.delivery_id)
        if delivery:
            if delivery.status != "failed":
                continue
            delivery.send_batch_id = send_batch_id
            delivery.broadcast_group_id = row.broadcast_group_id
            delivery.recipient_id = row.recipient_id
            delivery.phone_number = row.phone_number
            delivery.normalized_phone_number = row.phone_number
            delivery.template_name = template_name
            delivery.template_parameter_values = [
                message_content_1,
                message_content_2,
            ]
            delivery.status = "queued"
            delivery.status_updated_at = now
            delivery.provider_status_at = None
            delivery.provider_message_id = None
            delivery.provider_media_id = None
            delivery.error_message = None
            delivery.updated_at = now
        else:
            delivery = DocumentWhatsAppDeliveryModel(
                id=uuid.uuid4(),
                agency_id=batch.agency_id,
                group_id=batch.group_id,
                document_batch_id=document.batch_id,
                distributed_document_id=row.document_id,
                passenger_id=row.passenger_id,
                broadcast_group_id=row.broadcast_group_id,
                recipient_id=row.recipient_id,
                send_batch_id=send_batch_id,
                document_type=document.document_type,
                document_filename=row.document_filename,
                passenger_name=row.passenger_name,
                passport_number=row.passport_number,
                phone_number=row.phone_number,
                normalized_phone_number=row.phone_number,
                template_name=template_name,
                template_parameter_values=[
                    message_content_1,
                    message_content_2,
                ],
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
            detail="The selected documents were already claimed by another send",
        )
    await AuditLogRepository(session).record(
        action="document_whatsapp_broadcast_queued",
        entity_type="document_distribution_batch",
        entity_id=str(batch.id),
        agency_id=batch.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "group_id": str(batch.group_id),
            "document_type": batch.document_type,
            "send_batch_id": str(send_batch_id),
            "queued_count": queued_count,
            "explicit_resend_count": len(resend_ids),
            "message_content_lengths": [
                len(message_content_1),
                len(message_content_2),
            ],
        },
    )
    await session.commit()

    from app.infrastructure.whatsapp.tasks import (
        process_document_whatsapp_broadcast,
    )

    try:
        await publish_whatsapp_task(
            process_document_whatsapp_broadcast,
            payload={"send_batch_id": str(send_batch_id)},
        )
    except Exception as exc:
        failure_time = datetime.now(tz=UTC)
        await session.execute(
            update(DocumentWhatsAppDeliveryModel)
            .where(
                DocumentWhatsAppDeliveryModel.send_batch_id == send_batch_id,
                DocumentWhatsAppDeliveryModel.status == "queued",
            )
            .values(
                status="failed",
                status_updated_at=failure_time,
                updated_at=failure_time,
                error_message="The WhatsApp worker queue is temporarily unavailable",
            )
            .execution_options(synchronize_session=False)
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The WhatsApp worker queue is temporarily unavailable",
        ) from exc

    attempted_count = (
        len(requested_ids) if payload.document_ids is not None else len(preview.recipients)
    )
    return SendDocumentBroadcastResponse(
        send_batch_id=send_batch_id,
        queued_count=queued_count,
        skipped_count=max(0, attempted_count - queued_count),
        message=(
            f"Queued {queued_count} document{'' if queued_count == 1 else 's'} "
            "for individual WhatsApp delivery."
        ),
    )


@router.get(
    "/groups/{group_id}/whatsapp-deliveries/tracking",
    response_model=DocumentDeliveryTrackingResponse,
)
async def get_document_delivery_tracking(
    group_id: uuid.UUID,
    limit: Annotated[int, Query(ge=0, le=100)] = 100,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentDeliveryTrackingResponse:
    group = await _get_authorized_group(
        group_id,
        current_user=current_user,
        session=session,
    )
    count_result = await session.execute(
        select(
            DocumentWhatsAppDeliveryModel.status,
            func.count(DocumentWhatsAppDeliveryModel.id),
            func.max(DocumentWhatsAppDeliveryModel.status_updated_at),
        )
        .where(
            DocumentWhatsAppDeliveryModel.group_id == group.id,
            DocumentWhatsAppDeliveryModel.agency_id == group.agency_id,
        )
        .group_by(DocumentWhatsAppDeliveryModel.status)
    )
    count_rows = count_result.all()
    status_counts = {
        delivery_status: int(count) for delivery_status, count, _latest_update in count_rows
    }
    latest_status_updates = {
        delivery_status: latest_update
        for delivery_status, _count, latest_update in count_rows
        if latest_update is not None
    }
    deliveries: list[DocumentWhatsAppDeliveryModel] = []
    if limit:
        result = await session.execute(
            select(DocumentWhatsAppDeliveryModel)
            .where(
                DocumentWhatsAppDeliveryModel.group_id == group.id,
                DocumentWhatsAppDeliveryModel.agency_id == group.agency_id,
            )
            .order_by(DocumentWhatsAppDeliveryModel.status_updated_at.desc())
            .limit(limit)
        )
        deliveries = list(result.scalars().all())
    counts = DocumentDeliveryTrackingCounts(
        total=sum(status_counts.values()),
        queued=status_counts.get("queued", 0) + status_counts.get("processing", 0),
        sent=status_counts.get("submitted", 0) + status_counts.get("sent", 0),
        delivered=status_counts.get("delivered", 0),
        read=status_counts.get("read", 0),
        failed=status_counts.get("failed", 0),
        delivery_unknown=status_counts.get("delivery_unknown", 0),
    )
    return DocumentDeliveryTrackingResponse(
        group_id=group.id,
        counts=counts,
        poll_after_seconds=_document_delivery_poll_after_seconds(
            status_counts=status_counts,
            latest_status_updates=latest_status_updates,
            now=datetime.now(tz=UTC),
        ),
        deliveries=[
            DocumentDeliveryTrackingRow(
                delivery_id=delivery.id,
                passenger_id=delivery.passenger_id,
                passenger_name=delivery.passenger_name,
                passport_number=delivery.passport_number,
                document_type=delivery.document_type,
                document_filename=delivery.document_filename,
                phone_number=delivery.phone_number,
                status=delivery.status,
                error_message=delivery.error_message,
                status_updated_at=delivery.status_updated_at,
            )
            for delivery in deliveries
        ],
    )
