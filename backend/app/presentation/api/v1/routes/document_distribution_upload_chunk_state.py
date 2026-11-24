"""Distribution upload chunk state."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import PassportSubmission
from app.infrastructure.database.models import (
    DocumentDistributionBatchModel,
    DocumentUploadChunkModel,
)
from app.infrastructure.documents.storage_transfers import finish_cleanup_despite_cancellation
from app.presentation.api.v1.document_chunk_uploads import (
    DocumentChunkMetadata,
    validate_existing_document_chunk,
    validate_next_document_chunk,
)
from app.presentation.api.v1.routes.document_distribution_queries import (
    _all_group_documents,
)
from app.presentation.api.v1.routes.document_distribution_responses import _batch_response
from app.presentation.api.v1.routes.document_distribution_shared import (
    _processing_batch_response,
)
from app.presentation.api.v1.routes.document_distribution_storage import (
    _cleanup_remembered_request_staging,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DocumentBatchResponse,
)


@dataclass(frozen=True, slots=True)
class DistributionUploadChunkState:
    existing_batch: DocumentDistributionBatchModel | None
    chunk_completes_upload: bool
    replay_response: DocumentBatchResponse | None = None


async def read_distribution_upload_chunk(
    *,
    session: AsyncSession,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    document_type: str,
    chunk_metadata: DocumentChunkMetadata | None,
    incoming_file_count: int,
    chunk_byte_count: int,
    fingerprint: str | None,
    passengers: list[PassportSubmission],
) -> DistributionUploadChunkState:
    existing_batch: DocumentDistributionBatchModel | None = None

    existing_receipts: list[DocumentUploadChunkModel] = []

    chunk_completes_upload = True

    if chunk_metadata is not None:
        batch_result = await session.execute(
            select(DocumentDistributionBatchModel).where(
                DocumentDistributionBatchModel.id == chunk_metadata.upload_id,
                DocumentDistributionBatchModel.agency_id == agency_id,
                DocumentDistributionBatchModel.group_id == group_id,
                DocumentDistributionBatchModel.document_type == document_type,
            )
        )
        existing_batch = batch_result.scalar_one_or_none()
        if existing_batch is None:
            collision_result = await session.execute(
                select(DocumentDistributionBatchModel.id).where(
                    DocumentDistributionBatchModel.id == chunk_metadata.upload_id
                )
            )
            if collision_result.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The upload session is not available to this group",
                )
        receipt_result = await session.execute(
            select(DocumentUploadChunkModel).where(
                DocumentUploadChunkModel.id == chunk_metadata.chunk_id
            )
        )
        existing_receipt = receipt_result.scalar_one_or_none()
        if existing_receipt is not None:
            assert fingerprint is not None
            validate_existing_document_chunk(
                existing_receipt,
                metadata=chunk_metadata,
                agency_id=agency_id,
                workflow="distribution",
                group_id=group_id,
                document_type=document_type,
                fingerprint=fingerprint,
                file_count=incoming_file_count,
                byte_count=chunk_byte_count,
            )
            if existing_batch is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The upload session is not available to this group",
                )
            if existing_batch.status == "processing":
                await finish_cleanup_despite_cancellation(_cleanup_remembered_request_staging())
                return DistributionUploadChunkState(
                    existing_batch,
                    chunk_completes_upload,
                    _processing_batch_response(existing_batch),
                )
            documents = await _all_group_documents(
                session,
                group_id=group_id,
                agency_id=agency_id,
                document_type=document_type,
            )
            replay_response = await _batch_response(
                session=session,
                group_id=group_id,
                agency_id=agency_id,
                document_type=document_type,
                passengers=passengers,
                batch=existing_batch,
                documents=documents,
            )
            await finish_cleanup_despite_cancellation(_cleanup_remembered_request_staging())
            return DistributionUploadChunkState(
                existing_batch, chunk_completes_upload, replay_response
            )
        receipts_result = await session.execute(
            select(DocumentUploadChunkModel)
            .where(
                DocumentUploadChunkModel.upload_id == chunk_metadata.upload_id,
                DocumentUploadChunkModel.agency_id == agency_id,
                DocumentUploadChunkModel.workflow == "distribution",
                DocumentUploadChunkModel.group_id == group_id,
                DocumentUploadChunkModel.document_type == document_type,
            )
            .order_by(DocumentUploadChunkModel.chunk_index.asc())
        )
        existing_receipts = list(receipts_result.scalars().all())
        if (existing_batch is None) != (len(existing_receipts) == 0):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The upload session is incomplete and requires administrator review",
            )
        if existing_batch is not None and existing_batch.status != "processing":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This upload session is already complete",
            )
        chunk_completes_upload = validate_next_document_chunk(
            existing_receipts,
            metadata=chunk_metadata,
            incoming_file_count=incoming_file_count,
            incoming_byte_count=chunk_byte_count,
        )

    return DistributionUploadChunkState(existing_batch, chunk_completes_upload)
