"""Document distribution: queries."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentUploadChunkModel,
)
from app.infrastructure.documents.distribution_capacity import (
    MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE,
    enforce_distribution_scope_capacity,
)


async def _latest_document_batch(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    document_type: str,
) -> DocumentDistributionBatchModel | None:
    result = await session.execute(
        select(DocumentDistributionBatchModel)
        .where(
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.agency_id == agency_id,
            DocumentDistributionBatchModel.document_type == document_type,
        )
        .order_by(DocumentDistributionBatchModel.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _all_group_documents(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    document_type: str,
) -> list[DistributedDocumentModel]:
    result = await session.execute(
        select(DistributedDocumentModel)
        .where(
            DistributedDocumentModel.group_id == group_id,
            DistributedDocumentModel.agency_id == agency_id,
            DistributedDocumentModel.document_type == document_type,
        )
        .order_by(
            DistributedDocumentModel.created_at.desc(),
            DistributedDocumentModel.id.desc(),
        )
        .limit(MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE + 1)
    )
    documents = list(result.scalars().all())
    if len(documents) > MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This document list exceeds the supported "
                f"{MAX_DISTRIBUTION_ASSIGNMENT_ROWS_PER_SCOPE:,} assignment limit. "
                "Remove obsolete documents before continuing."
            ),
        )
    return documents


async def _enforce_group_document_assignment_capacity(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    document_type: str,
    incoming_rows: int,
) -> None:
    """Fail before ORM staging when a locked distribution ledger is full."""

    result = await session.execute(
        select(func.count(DistributedDocumentModel.id)).where(
            DistributedDocumentModel.group_id == group_id,
            DistributedDocumentModel.agency_id == agency_id,
            DistributedDocumentModel.document_type == document_type,
        )
    )
    enforce_distribution_scope_capacity(
        existing_rows=int(result.scalar_one()),
        incoming_rows=incoming_rows,
    )


async def _first_blocking_processing_upload_id(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    document_type: str,
    exclude_upload_id: uuid.UUID,
    lock: bool = False,
) -> uuid.UUID | None:
    """Find a different incomplete upload without leaking another scope."""

    statement = (
        select(DocumentDistributionBatchModel.id)
        .where(
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.agency_id == agency_id,
            DocumentDistributionBatchModel.document_type == document_type,
            DocumentDistributionBatchModel.status == "processing",
            DocumentDistributionBatchModel.id != exclude_upload_id,
        )
        .order_by(
            DocumentDistributionBatchModel.created_at.asc(),
            DocumentDistributionBatchModel.id.asc(),
        )
        .limit(1)
    )
    if lock:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def _refresh_distribution_batches(
    session: AsyncSession,
    *,
    batch_ids: set[uuid.UUID],
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    now: datetime,
) -> None:
    if not batch_ids:
        return
    batches_result = await session.execute(
        select(DocumentDistributionBatchModel)
        .where(
            DocumentDistributionBatchModel.id.in_(batch_ids),
            DocumentDistributionBatchModel.agency_id == agency_id,
            DocumentDistributionBatchModel.group_id == group_id,
        )
        .with_for_update()
    )
    batches = list(batches_result.scalars().all())
    if not batches:
        return
    processing_batch_ids = {batch.id for batch in batches if batch.status == "processing"}
    incomplete_processing_ids = set(processing_batch_ids)
    if processing_batch_ids:
        receipts_result = await session.execute(
            select(
                DocumentUploadChunkModel.upload_id,
                DocumentUploadChunkModel.chunk_index,
                DocumentUploadChunkModel.expected_chunk_count,
                DocumentUploadChunkModel.expected_file_count,
                DocumentUploadChunkModel.file_count,
            ).where(
                DocumentUploadChunkModel.upload_id.in_(processing_batch_ids),
                DocumentUploadChunkModel.agency_id == agency_id,
                DocumentUploadChunkModel.workflow == "distribution",
                DocumentUploadChunkModel.group_id == group_id,
            )
        )
        manifests: dict[uuid.UUID, list[tuple[int, int, int, int]]] = {}
        for upload_id, chunk_index, chunk_count, file_count, chunk_files in receipts_result.all():
            manifests.setdefault(upload_id, []).append(
                (chunk_index, chunk_count, file_count, chunk_files)
            )
        for upload_id, manifest in manifests.items():
            ordered = sorted(manifest)
            expected_chunks = ordered[0][1]
            expected_files = ordered[0][2]
            complete = (
                len(ordered) == expected_chunks
                and [item[0] for item in ordered] == list(range(expected_chunks))
                and all(
                    item[1] == expected_chunks and item[2] == expected_files for item in ordered
                )
                and sum(item[3] for item in ordered) == expected_files
            )
            if complete:
                incomplete_processing_ids.discard(upload_id)
    remaining_result = await session.execute(
        select(
            DistributedDocumentModel.batch_id,
            DistributedDocumentModel.match_status,
        ).where(
            DistributedDocumentModel.batch_id.in_([batch.id for batch in batches]),
            DistributedDocumentModel.agency_id == agency_id,
            DistributedDocumentModel.group_id == group_id,
        )
    )
    counts_by_batch: dict[uuid.UUID, tuple[int, int]] = {}
    for batch_id, match_status in remaining_result.all():
        uploaded_count, matched_count = counts_by_batch.get(batch_id, (0, 0))
        counts_by_batch[batch_id] = (
            uploaded_count + 1,
            matched_count + int(match_status == "matched"),
        )
    for batch in batches:
        uploaded_count, matched_count = counts_by_batch.get(batch.id, (0, 0))
        batch.status = "processing" if batch.id in incomplete_processing_ids else "draft"
        batch.saved_at = None
        batch.uploaded_count = uploaded_count
        batch.matched_count = matched_count
        batch.updated_at = now
