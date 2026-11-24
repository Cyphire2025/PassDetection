"""Scoped batch reads and transactional durable batch deletion."""

from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging.logger import get_logger
from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    DocumentRenameBatchModel,
    DocumentRenameItemModel,
    DocumentUploadChunkModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.document_rename_queries import (
    rename_batches_query,
    rename_items_query,
)
from app.presentation.api.v1.routes.document_rename_batch_contracts import RenameBatchServices
from app.presentation.api.v1.schemas.document_rename_schemas import (
    DeleteRenameBatchesRequest,
    DeleteRenameBatchesResponse,
    RenameDocumentBatchResponse,
    RenameDocumentBatchSummaryResponse,
)
from app.presentation.dependencies.auth import get_current_active_user

logger = get_logger("app.presentation.api.v1.routes.document_rename")


async def list_rename_batches(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    *,
    services: RenameBatchServices,
) -> list[RenameDocumentBatchSummaryResponse]:
    agency_id = services.ensure_allowed(current_user)
    result = await session.execute(
        rename_batches_query(user_id=current_user.id, role=current_user.role, agency_id=agency_id)
        .order_by(DocumentRenameBatchModel.created_at.desc())
        .limit(100)
    )
    return [services.summary_response(batch) for batch in result.scalars().all()]


async def get_rename_batch(
    batch_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    *,
    services: RenameBatchServices,
) -> RenameDocumentBatchResponse:
    agency_id = services.ensure_allowed(current_user)
    batch_result = await session.execute(
        rename_batches_query(
            user_id=current_user.id, role=current_user.role, agency_id=agency_id
        ).where(DocumentRenameBatchModel.id == batch_id)
    )
    batch = batch_result.scalar_one_or_none()
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Rename batch was not found"
        )
    items_result = await session.execute(rename_items_query(batch.id, agency_id))
    return await services.batch_response(batch, list(items_result.scalars().all()))


async def delete_rename_batches(
    payload: DeleteRenameBatchesRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    *,
    services: RenameBatchServices,
) -> DeleteRenameBatchesResponse:
    agency_id = services.ensure_allowed(current_user)
    batch_ids = list(dict.fromkeys(payload.batch_ids))
    batch_result = await session.execute(
        select(DocumentRenameBatchModel)
        .where(
            DocumentRenameBatchModel.id.in_(batch_ids),
            *services.batch_filters(current_user, agency_id),
        )
        .order_by(DocumentRenameBatchModel.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    batches = list(batch_result.scalars().all())
    if not batches:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No rename batches were found"
        )
    found_batch_ids = [batch.id for batch in batches]
    items_result = await session.execute(
        select(DocumentRenameItemModel)
        .where(
            DocumentRenameItemModel.batch_id.in_(found_batch_ids),
            DocumentRenameItemModel.agency_id == agency_id,
        )
        .order_by(DocumentRenameItemModel.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    items = list(items_result.scalars().all())
    receipts_result = await session.execute(
        select(DocumentUploadChunkModel)
        .where(
            DocumentUploadChunkModel.upload_id.in_(found_batch_ids),
            DocumentUploadChunkModel.agency_id == agency_id,
            DocumentUploadChunkModel.workflow == "rename",
        )
        .order_by(DocumentUploadChunkModel.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    receipts = list(receipts_result.scalars().all())
    storage_keys = list({item.storage_key for item in items if item.storage_key})
    cleanup_jobs = services.stage_cleanup(
        session,
        agency_id=agency_id,
        source="document_rename_batch_delete",
        context_id=",".join((str(batch_id) for batch_id in sorted(found_batch_ids, key=str))),
        storage_keys=storage_keys,
    )
    for receipt in receipts:
        await session.delete(receipt)
    for batch in batches:
        await session.delete(batch)
    await services.audit_factory(session).record(
        action="document_rename_deleted",
        entity_type="document_rename_batch",
        entity_id="bulk",
        agency_id=agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "requested_count": len(batch_ids),
            "deleted_count": len(batches),
            "deleted_item_count": len(items),
            "deleted_upload_receipt_count": len(receipts),
            "storage_cleanup_object_count": len(storage_keys),
        },
    )
    await session.commit()
    cleanup_results = []
    for cleanup_job in cleanup_jobs:
        try:
            cleanup_result = await services.process_cleanup(cleanup_job.id)
            if cleanup_result is not None:
                cleanup_results.append(cleanup_result)
        except Exception as exc:
            logger.warning(
                "document_rename_cleanup_runner_deferred",
                cleanup_job_id=str(cleanup_job.id),
                object_count=cleanup_job.object_count,
                error_type=type(exc).__name__,
            )
    deleted_storage_objects = sum(
        (result.deleted_count for result in cleanup_results if result.completed)
    )
    return DeleteRenameBatchesResponse(
        deleted_count=len(batches), deleted_storage_objects=deleted_storage_objects
    )
