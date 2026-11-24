"""Bounded upload reads and immutable chunk preflight/replay checks."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    DocumentRenameBatchModel,
    DocumentRenameItemModel,
    DocumentUploadChunkModel,
)
from app.infrastructure.security.upload_security import UploadSecurityContext
from app.presentation.api.v1.document_chunk_uploads import (
    document_chunk_fingerprint,
    validate_existing_document_chunk,
    validate_next_document_chunk,
)
from app.presentation.api.v1.routes.document_rename_upload_contracts import (
    DocumentChunkMetadata,
    PreparedRenameUpload,
    RenamePreparationServices,
)
from app.presentation.api.v1.schemas.document_rename_schemas import (
    RenameDocumentBatchResponse,
)


async def prepare_rename_upload(
    files: list[UploadFile],
    title: str,
    current_user: User,
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    actor_id: uuid.UUID,
    expected_actor_role: UserRole,
    chunk_metadata: DocumentChunkMetadata | None,
    services: RenamePreparationServices,
) -> PreparedRenameUpload | RenameDocumentBatchResponse:
    # Release the authentication read transaction before scanning, parsing or
    # object storage. The finalization phase reauthorizes under row locks.
    await session.rollback()
    uploads = await services.read_uploads(
        files,
        security_context=UploadSecurityContext(
            ingestion_flow="document_rename", agency_id=agency_id, user_id=actor_id
        ),
    )
    chunk_byte_count = sum((len(upload.content) for upload in uploads))
    fingerprint = document_chunk_fingerprint(uploads) if chunk_metadata else None
    batch_id = chunk_metadata.upload_id if chunk_metadata else uuid.uuid4()
    existing_batch: DocumentRenameBatchModel | None = None
    if chunk_metadata is not None:
        batch_result = await session.execute(
            select(DocumentRenameBatchModel).where(
                DocumentRenameBatchModel.id == batch_id,
                *services.batch_filters(current_user, agency_id),
            )
        )
        existing_batch = batch_result.scalar_one_or_none()
    if chunk_metadata is not None and existing_batch is None:
        collision_result = await session.execute(
            select(DocumentRenameBatchModel.id).where(DocumentRenameBatchModel.id == batch_id)
        )
        if collision_result.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The upload session is not available to this account",
            )
    if (
        chunk_metadata is not None
        and existing_batch is not None
        and (existing_batch.title != title)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The upload session title does not match its first chunk",
        )
    existing_receipts: list[DocumentUploadChunkModel] = []
    if chunk_metadata is not None:
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
                workflow="rename",
                group_id=None,
                document_type=None,
                fingerprint=fingerprint,
                file_count=len(uploads),
                byte_count=chunk_byte_count,
            )
            if existing_batch is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="The upload session is not available to this account",
                )
            if existing_batch.status != "completed":
                return await services.batch_response(existing_batch, [])
            items_result = await session.execute(
                select(DocumentRenameItemModel)
                .where(
                    DocumentRenameItemModel.batch_id == existing_batch.id,
                    DocumentRenameItemModel.agency_id == agency_id,
                )
                .order_by(DocumentRenameItemModel.renamed_filename.asc())
            )
            return await services.batch_response(existing_batch, list(items_result.scalars().all()))
        receipts_result = await session.execute(
            select(DocumentUploadChunkModel)
            .where(
                DocumentUploadChunkModel.upload_id == chunk_metadata.upload_id,
                DocumentUploadChunkModel.agency_id == agency_id,
                DocumentUploadChunkModel.workflow == "rename",
            )
            .order_by(DocumentUploadChunkModel.chunk_index.asc())
        )
        existing_receipts = list(receipts_result.scalars().all())
        if (existing_batch is None) != (len(existing_receipts) == 0):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The upload session is incomplete and requires administrator review",
            )
        if existing_batch is not None and existing_batch.status == "completed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This upload session is already complete",
            )
        validate_next_document_chunk(
            existing_receipts,
            metadata=chunk_metadata,
            incoming_file_count=len(uploads),
            incoming_byte_count=chunk_byte_count,
        )
    used_names: set[str] = set()
    if existing_batch is not None:
        items_result = await session.execute(
            select(DocumentRenameItemModel).where(
                DocumentRenameItemModel.batch_id == existing_batch.id,
                DocumentRenameItemModel.agency_id == agency_id,
            )
        )
        used_names = {item.renamed_filename for item in items_result.scalars().all()}
    if chunk_metadata is not None:
        await session.rollback()
    return PreparedRenameUpload(
        agency_id,
        actor_id,
        expected_actor_role,
        title,
        chunk_metadata,
        uploads,
        chunk_byte_count,
        fingerprint,
        batch_id,
        existing_batch,
        used_names,
    )
