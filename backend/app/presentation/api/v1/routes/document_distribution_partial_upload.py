"""Preserve committed replacements when an incomplete upload is discarded."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentUploadChunkModel,
    UserModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    AbortDocumentUploadResponse,
)


async def retain_partial_replacement_upload(
    session: AsyncSession, *, batch: DocumentDistributionBatchModel,
    documents: list[DistributedDocumentModel], receipts: list[DocumentUploadChunkModel],
    actor: User | UserModel, group_id: uuid.UUID, agency_id: uuid.UUID, document_type: str,
    audit: AuditLogRepository,
) -> AbortDocumentUploadResponse:
    batch_id = batch.id
    # Earlier chunks atomically replaced their originals. Discarding those
    # committed new copies would lose both versions; finish the partial
    # upload as a reviewable draft instead, without requiring stale receipts.
    batch.status = "draft"
    batch.uploaded_count = len(documents)
    batch.matched_count = sum(document.match_status == "matched" for document in documents)
    batch.rejected_count = sum(receipt.rejected_count for receipt in receipts)
    batch.saved_at = None
    batch.updated_at = datetime.now(tz=UTC)
    remaining_processing_upload_ids = list((await session.scalars(
        select(DocumentDistributionBatchModel.id)
        .where(
            DocumentDistributionBatchModel.agency_id == agency_id,
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.document_type == document_type,
            DocumentDistributionBatchModel.status == "processing",
            DocumentDistributionBatchModel.id != batch_id,
        )
        .order_by(DocumentDistributionBatchModel.id)
        .with_for_update()
    )).all())
    await audit.record(
        action="document_distribution_partial_replacements_retained",
        entity_type="document_distribution_batch",
        entity_id=str(batch_id),
        agency_id=agency_id,
        user_id=actor.id,
        actor_email=actor.email,
        metadata={
            "group_id": str(group_id),
            "document_type": document_type,
            "retained_document_count": len(documents),
            "retained_chunk_count": len(receipts),
        },
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return AbortDocumentUploadResponse(
        batch_id=batch_id,
        status="partial_retained",
        retained_document_count=len(documents),
        deleted_document_count=0,
        deleted_chunk_count=0,
        deleted_storage_object_count=0,
        storage_cleanup_pending=False,
        remaining_processing_upload_ids=remaining_processing_upload_ids,
    )
