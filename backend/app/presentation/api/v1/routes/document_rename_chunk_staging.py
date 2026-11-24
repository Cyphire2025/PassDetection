"""Serialized chunk receipts, ownership, replay and completion decisions."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    DocumentRenameBatchModel,
    DocumentRenameItemModel,
    DocumentUploadChunkModel,
    UserModel,
)
from app.presentation.api.v1.document_chunk_uploads import (
    acquire_document_upload_advisory_lock,
    new_document_chunk_receipt,
    resolve_concurrent_document_chunk_replay,
    validate_next_document_chunk,
)
from app.presentation.api.v1.routes.document_rename_upload_contracts import (
    PreparedRenameUpload,
    RenameFinalizationServices,
    StagedRenameUpload,
)
from app.presentation.api.v1.routes.document_rename_values import _role_value
from app.presentation.api.v1.schemas.document_rename_schemas import (
    RenameDocumentBatchResponse,
)


async def stage_rename_chunk(
    prepared: PreparedRenameUpload,
    staged: StagedRenameUpload,
    actor: UserModel | User,
    session: AsyncSession,
    *,
    services: RenameFinalizationServices,
) -> tuple[DocumentRenameBatchModel, bool, RenameDocumentBatchResponse | None]:
    agency_id = prepared.agency_id
    title = prepared.title
    chunk_metadata = prepared.chunk_metadata
    uploads = prepared.uploads
    chunk_byte_count = prepared.chunk_byte_count
    fingerprint = prepared.fingerprint
    batch_id = prepared.batch_id
    existing_batch = prepared.existing_batch
    batch = staged.batch
    items = staged.items
    uploaded_keys = staged.uploaded_keys
    storage = staged.storage
    assert chunk_metadata is not None
    await acquire_document_upload_advisory_lock(
        session, workflow="rename", upload_id=chunk_metadata.upload_id
    )
    serialized_batch_result = await session.execute(
        select(DocumentRenameBatchModel)
        .where(DocumentRenameBatchModel.id == batch_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    serialized_batch = serialized_batch_result.scalar_one_or_none()
    if serialized_batch is not None:
        owner_mismatch = (
            _role_value(actor.role) == UserRole.AGENCY_STAFF.value
            and serialized_batch.created_by_user_id != actor.id
        )
        if serialized_batch.agency_id != agency_id or owner_mismatch:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The upload session is not available to this account",
            )
        if serialized_batch.title != title:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The upload session title does not match its first chunk",
            )
        batch = serialized_batch
    locked_receipts_result = await session.execute(
        select(DocumentUploadChunkModel)
        .where(
            DocumentUploadChunkModel.upload_id == chunk_metadata.upload_id,
            DocumentUploadChunkModel.workflow == "rename",
        )
        .order_by(DocumentUploadChunkModel.chunk_index.asc())
        .with_for_update()
    )
    locked_receipts = list(locked_receipts_result.scalars().all())
    assert fingerprint is not None
    concurrent_replay = resolve_concurrent_document_chunk_replay(
        locked_receipts,
        metadata=chunk_metadata,
        agency_id=agency_id,
        workflow="rename",
        group_id=None,
        document_type=None,
        fingerprint=fingerprint,
        file_count=len(uploads),
        byte_count=chunk_byte_count,
    )
    if concurrent_replay is not None:
        if serialized_batch is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The committed upload session is no longer available",
            )
        replay_items: list[DocumentRenameItemModel] = []
        if serialized_batch.status == "completed":
            replay_items_result = await session.execute(
                select(DocumentRenameItemModel)
                .where(
                    DocumentRenameItemModel.batch_id == batch_id,
                    DocumentRenameItemModel.agency_id == agency_id,
                )
                .order_by(DocumentRenameItemModel.renamed_filename.asc())
            )
            replay_items = list(replay_items_result.scalars().all())
        replay_response = await services.batch_response(serialized_batch, replay_items)
        await session.rollback()
        await services.cleanup(storage, uploaded_keys, agency_id=agency_id, batch_id=batch_id)
        return (batch, True, replay_response)
    if serialized_batch is not None and existing_batch is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The upload session is incomplete and requires administrator review",
        )
    if serialized_batch is None and existing_batch is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="The upload session is no longer available"
        )
    complete = validate_next_document_chunk(
        locked_receipts,
        metadata=chunk_metadata,
        incoming_file_count=len(uploads),
        incoming_byte_count=chunk_byte_count,
    )
    session.add(
        new_document_chunk_receipt(
            metadata=chunk_metadata,
            agency_id=agency_id,
            workflow="rename",
            group_id=None,
            document_type=None,
            fingerprint=fingerprint,
            file_count=len(uploads),
            byte_count=chunk_byte_count,
            accepted_count=sum((1 for item in items if item.detected_type != "unknown")),
            rejected_count=sum((1 for item in items if item.detected_type == "unknown")),
        )
    )
    return batch, complete, None
