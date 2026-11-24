"""Distribution upload commit."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.documents.distribution_ingestion import (
    TravelDocumentIngestionResult,
)
from app.infrastructure.documents.storage_cleanup import process_storage_cleanup_job
from app.infrastructure.documents.storage_transfers import finish_cleanup_despite_cancellation
from app.presentation.api.v1.document_chunk_uploads import (
    DocumentChunkMetadata,
    new_document_chunk_receipt,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    logger,
)
from app.presentation.api.v1.routes.document_distribution_storage import (
    _cleanup_distribution_storage_keys,
    _cleanup_remembered_request_staging,
)


async def commit_distribution_upload(
    *,
    session: AsyncSession,
    ingestion: TravelDocumentIngestionResult,
    chunk_metadata: DocumentChunkMetadata | None,
    chunk_completes_upload: bool,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    document_type: str,
    fingerprint: str | None,
    incoming_file_count: int,
    chunk_byte_count: int,
    replacement_cleanup_ids: list[uuid.UUID],
) -> None:
    if chunk_metadata is not None:
        ingestion.batch.status = "draft" if chunk_completes_upload else "processing"
        assert fingerprint is not None
        session.add(
            new_document_chunk_receipt(
                metadata=chunk_metadata,
                agency_id=agency_id,
                workflow="distribution",
                group_id=group_id,
                document_type=document_type,
                fingerprint=fingerprint,
                file_count=incoming_file_count,
                byte_count=chunk_byte_count,
                accepted_count=incoming_file_count - len(ingestion.rejected),
                rejected_count=len(ingestion.rejected),
                rejected_documents=[
                    {
                        "filename": item.filename,
                        "detected_type": item.detected_type,
                        "reason": item.reason,
                    }
                    for item in ingestion.rejected
                ],
            )
        )
        try:
            await session.flush()
        except BaseException:
            await session.rollback()
            await _cleanup_distribution_storage_keys(
                list(ingestion.created_storage_keys),
                agency_id=agency_id,
                group_id=group_id,
                document_type=document_type,
            )
            raise

    try:
        await session.commit()
    except BaseException:
        # COMMIT acknowledgement can be lost after PostgreSQL made the rows
        # durable. Keep objects that those rows may reference for safe
        # operational reconciliation; remove only proven orphaned keys.
        await session.rollback()
        logger.warning(
            "document_distribution_commit_outcome_ambiguous",
            group_id=str(group_id),
            document_type=document_type,
            object_count=len(ingestion.created_storage_keys),
        )
        raise

    await finish_cleanup_despite_cancellation(_cleanup_remembered_request_staging())

    for cleanup_id in replacement_cleanup_ids:
        try:
            await process_storage_cleanup_job(cleanup_id)
        except Exception as exc:
            logger.warning(
                "document_distribution_replacement_cleanup_deferred",
                cleanup_job_id=str(cleanup_id),
                error_type=type(exc).__name__,
            )
