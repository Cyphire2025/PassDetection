"""Document distribution: responses."""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import PassportSubmission
from app.infrastructure.database.email_models import EmailArtifactDocumentModel
from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentUploadChunkModel,
    DocumentWhatsAppDeliveryModel,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.document_distribution_shared import (
    DOCUMENT_DELIVERY_ACCEPTED_STATUSES,
    DOCUMENT_DELIVERY_IN_PROGRESS_STATUSES,
    DOCUMENT_RESPONSE_RENDER_WINDOW,
    _passenger_review_rows,
    _physical_file_accounting,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DistributedDocumentResponse,
    DocumentBatchResponse,
    RejectedDocumentResponse,
)


async def _document_response(
    document: DistributedDocumentModel,
    storage: MinioStorageRepository,
    *,
    source: str,
    deliveries: list[DocumentWhatsAppDeliveryModel],
) -> DistributedDocumentResponse:
    ordered_deliveries = sorted(
        deliveries,
        key=lambda item: (item.status_updated_at, item.created_at, str(item.id)),
        reverse=True,
    )
    latest_delivery = ordered_deliveries[0] if ordered_deliveries else None
    accepted_deliveries = [
        item for item in ordered_deliveries if item.status in DOCUMENT_DELIVERY_ACCEPTED_STATUSES
    ]
    latest_accepted = accepted_deliveries[0] if accepted_deliveries else None
    in_progress = any(
        item.status in DOCUMENT_DELIVERY_IN_PROGRESS_STATUSES for item in ordered_deliveries
    )
    if latest_accepted is not None:
        delivery_status = "sent"
    elif latest_delivery is not None:
        delivery_status = latest_delivery.status
    else:
        delivery_status = "not_sent"
    return DistributedDocumentResponse(
        id=document.id,
        original_filename=document.original_filename,
        document_type=document.document_type,
        detected_type=document.detected_type,
        match_status=document.match_status,
        match_confidence=document.match_confidence,
        match_reason=document.match_reason,
        extracted_name=document.extracted_name,
        extracted_passport_number=document.extracted_passport_number,
        extracted_reference=document.extracted_reference,
        source=source,
        delivery_status=delivery_status,
        sent_to=latest_accepted.phone_number if latest_accepted else None,
        last_sent_at=latest_accepted.status_updated_at if latest_accepted else None,
        can_resend=latest_accepted is not None and not in_progress,
        url=await storage.get_presigned_url(document.storage_key),
    )


async def _batch_response(
    *,
    session: AsyncSession,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    document_type: str,
    passengers: list[PassportSubmission],
    batch: DocumentDistributionBatchModel | None,
    documents: list[DistributedDocumentModel],
    rejected_documents: list[RejectedDocumentResponse] | None = None,
) -> DocumentBatchResponse:
    storage = MinioStorageRepository()
    batches_result = await session.execute(
        select(DocumentDistributionBatchModel)
        .where(
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.agency_id == agency_id,
            DocumentDistributionBatchModel.document_type == document_type,
        )
        .order_by(DocumentDistributionBatchModel.created_at.desc())
    )
    all_batches = list(batches_result.scalars().all())
    pending_batches = [item for item in all_batches if item.status != "saved"]
    processing_batches = [item for item in all_batches if item.status == "processing"]
    response_batch = (
        processing_batches[0]
        if processing_batches
        else pending_batches[0]
        if pending_batches
        else batch or (all_batches[0] if all_batches else None)
    )
    document_ids = [document.id for document in documents]
    deliveries_by_document: dict[uuid.UUID, list[DocumentWhatsAppDeliveryModel]] = {}
    email_document_ids: set[uuid.UUID] = set()
    if document_ids:
        delivery_result = await session.execute(
            select(DocumentWhatsAppDeliveryModel).where(
                DocumentWhatsAppDeliveryModel.distributed_document_id.in_(document_ids),
                DocumentWhatsAppDeliveryModel.agency_id == agency_id,
                DocumentWhatsAppDeliveryModel.group_id == group_id,
            )
        )
        for delivery in delivery_result.scalars().all():
            if delivery.distributed_document_id is not None:
                deliveries_by_document.setdefault(
                    delivery.distributed_document_id,
                    [],
                ).append(delivery)
        email_link_result = await session.execute(
            select(EmailArtifactDocumentModel.distributed_document_id).where(
                EmailArtifactDocumentModel.distributed_document_id.in_(document_ids)
            )
        )
        email_document_ids = set(email_link_result.scalars().all())

    response_documents = list(documents)
    presign_slots = asyncio.Semaphore(16)

    async def render_document(
        document: DistributedDocumentModel,
    ) -> DistributedDocumentResponse:
        async with presign_slots:
            return await _document_response(
                document,
                storage,
                source="email" if document.id in email_document_ids else "manual",
                deliveries=deliveries_by_document.get(document.id, []),
            )

    rendered_documents: list[DistributedDocumentResponse] = []
    for offset in range(0, len(response_documents), DOCUMENT_RESPONSE_RENDER_WINDOW):
        rendered_documents.extend(
            await asyncio.gather(
                *(
                    render_document(document)
                    for document in response_documents[
                        offset : offset + DOCUMENT_RESPONSE_RENDER_WINDOW
                    ]
                )
            )
        )
    persisted_rejections: list[RejectedDocumentResponse] = []
    if (
        response_batch is not None
        and getattr(response_batch, "rejected_count", 0) > 0
        and not rejected_documents
    ):
        receipts_result = await session.execute(
            select(DocumentUploadChunkModel.rejected_documents)
            .where(
                DocumentUploadChunkModel.upload_id == response_batch.id,
                DocumentUploadChunkModel.agency_id == agency_id,
                DocumentUploadChunkModel.workflow == "distribution",
                DocumentUploadChunkModel.group_id == group_id,
                DocumentUploadChunkModel.document_type == document_type,
            )
            .order_by(DocumentUploadChunkModel.chunk_index.asc())
        )
        for chunk_rejections in receipts_result.scalars().all():
            for item in chunk_rejections if isinstance(chunk_rejections, list) else []:
                if not isinstance(item, dict):
                    continue
                filename = item.get("filename")
                detected_type = item.get("detected_type")
                reason = item.get("reason")
                if not isinstance(filename, str):
                    continue
                if not isinstance(detected_type, str):
                    continue
                if not isinstance(reason, str):
                    continue
                persisted_rejections.append(
                    RejectedDocumentResponse(
                        filename=filename,
                        detected_type=detected_type,
                        reason=reason,
                    )
                )
    responses_by_document = {
        document.id: response
        for document, response in zip(response_documents, rendered_documents, strict=True)
    }

    rows, unmatched, matched_count = _passenger_review_rows(
        passengers=passengers,
        documents=documents,
        responses_by_document=responses_by_document,
    )
    physical_file_count, assigned_file_count, assigned_passenger_count, assignment_issues = (
        _physical_file_accounting(
            passengers=passengers,
            documents=documents,
            responses_by_document=responses_by_document,
        )
    )
    visible_documents = response_documents
    return DocumentBatchResponse(
        batch_id=response_batch.id if response_batch else None,
        group_id=group_id,
        document_type=document_type,
        status=response_batch.status if response_batch else "draft",
        uploaded_count=len(visible_documents),
        rejected_count=response_batch.rejected_count if response_batch else 0,
        matched_count=matched_count,
        physical_file_count=physical_file_count,
        assigned_file_count=assigned_file_count,
        assigned_passenger_count=assigned_passenger_count,
        needs_assignment_count=len(assignment_issues),
        processing_upload_ids=[item.id for item in processing_batches],
        saved_at=response_batch.saved_at if response_batch else None,
        created_at=response_batch.created_at if response_batch else None,
        review_rows=rows,
        unmatched_documents=unmatched,
        assignment_issues=assignment_issues,
        rejected_documents=persisted_rejections or rejected_documents or [],
    )
