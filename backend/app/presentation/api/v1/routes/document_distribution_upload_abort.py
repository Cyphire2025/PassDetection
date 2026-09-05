"""Document distribution: upload abort."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.domain.value_objects.travel_document_taxonomy import DOCUMENT_TYPES
from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentUploadChunkModel,
    DocumentWhatsAppDeliveryModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.storage_cleanup import (
    process_storage_cleanup_job,
    stage_storage_cleanup_jobs,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.document_chunk_uploads import (
    acquire_document_upload_advisory_lock,
    acquire_document_upload_scope_advisory_lock,
)
from app.presentation.api.v1.routes.document_distribution_scope import (
    _get_authorized_group,
    _lock_active_document_scope,
)
from app.presentation.api.v1.routes.document_distribution_shared import logger
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    AbortDocumentUploadResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.post(
    "/groups/{group_id}/{document_type}/uploads/{batch_id}/abort",
    response_model=AbortDocumentUploadResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def abort_incomplete_distribution_upload(
    group_id: uuid.UUID,
    document_type: str,
    batch_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> AbortDocumentUploadResponse:
    """Discard one incomplete upload without affecting any completed batch."""

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
    actor, _ = await _lock_active_document_scope(
        session,
        current_user=current_user,
        group_id=group_id,
        agency_id=group.agency_id,
    )
    await acquire_document_upload_scope_advisory_lock(
        session,
        agency_id=group.agency_id,
        group_id=group_id,
        document_type=document_type,
    )
    await acquire_document_upload_advisory_lock(
        session,
        workflow="distribution",
        upload_id=batch_id,
    )

    batch_result = await session.execute(
        select(DocumentDistributionBatchModel)
        .where(
            DocumentDistributionBatchModel.id == batch_id,
            DocumentDistributionBatchModel.agency_id == group.agency_id,
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.document_type == document_type,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    batch = batch_result.scalar_one_or_none()
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Incomplete document upload was not found",
        )
    if batch.status != "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only an incomplete processing upload can be discarded",
        )

    receipts_result = await session.execute(
        select(DocumentUploadChunkModel)
        .where(
            DocumentUploadChunkModel.upload_id == batch_id,
            DocumentUploadChunkModel.agency_id == group.agency_id,
            DocumentUploadChunkModel.workflow == "distribution",
            DocumentUploadChunkModel.group_id == group_id,
            DocumentUploadChunkModel.document_type == document_type,
        )
        .order_by(
            DocumentUploadChunkModel.chunk_index.asc(),
            DocumentUploadChunkModel.id.asc(),
        )
        .with_for_update()
    )
    receipts = list(receipts_result.scalars().all())
    documents_result = await session.execute(
        select(DistributedDocumentModel)
        .where(
            DistributedDocumentModel.batch_id == batch_id,
            DistributedDocumentModel.agency_id == group.agency_id,
            DistributedDocumentModel.group_id == group_id,
            DistributedDocumentModel.document_type == document_type,
        )
        .order_by(DistributedDocumentModel.id.asc())
        .with_for_update()
    )
    documents = list(documents_result.scalars().all())

    delivery_result = await session.execute(
        select(DocumentWhatsAppDeliveryModel.id)
        .where(
            DocumentWhatsAppDeliveryModel.document_batch_id == batch_id,
            DocumentWhatsAppDeliveryModel.agency_id == group.agency_id,
            DocumentWhatsAppDeliveryModel.group_id == group_id,
            DocumentWhatsAppDeliveryModel.document_type == document_type,
        )
        .order_by(DocumentWhatsAppDeliveryModel.id.asc())
        .with_for_update()
        .limit(1)
    )
    if delivery_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This upload has delivery history and cannot be discarded",
        )

    candidate_storage_keys = sorted({document.storage_key for document in documents})
    still_used_storage_keys: set[str] = set()
    if candidate_storage_keys:
        remaining_key_result = await session.execute(
            select(DistributedDocumentModel.storage_key)
            .where(
                DistributedDocumentModel.storage_key.in_(candidate_storage_keys),
                DistributedDocumentModel.batch_id != batch_id,
            )
            .order_by(DistributedDocumentModel.storage_key.asc())
            .with_for_update()
        )
        still_used_storage_keys = set(remaining_key_result.scalars().all())
    delete_storage_keys = [
        key for key in candidate_storage_keys if key not in still_used_storage_keys
    ]
    cleanup_jobs = stage_storage_cleanup_jobs(
        session,
        agency_id=group.agency_id,
        source="document_distribution_abort",
        context_id=str(batch_id),
        storage_keys=delete_storage_keys,
    )

    await session.execute(
        delete(DistributedDocumentModel)
        .where(
            DistributedDocumentModel.batch_id == batch_id,
            DistributedDocumentModel.agency_id == group.agency_id,
            DistributedDocumentModel.group_id == group_id,
            DistributedDocumentModel.document_type == document_type,
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        delete(DocumentUploadChunkModel)
        .where(
            DocumentUploadChunkModel.upload_id == batch_id,
            DocumentUploadChunkModel.agency_id == group.agency_id,
            DocumentUploadChunkModel.workflow == "distribution",
            DocumentUploadChunkModel.group_id == group_id,
            DocumentUploadChunkModel.document_type == document_type,
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        delete(DocumentDistributionBatchModel)
        .where(
            DocumentDistributionBatchModel.id == batch_id,
            DocumentDistributionBatchModel.agency_id == group.agency_id,
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.document_type == document_type,
            DocumentDistributionBatchModel.status == "processing",
        )
        .execution_options(synchronize_session=False)
    )
    remaining_result = await session.execute(
        select(DocumentDistributionBatchModel.id)
        .where(
            DocumentDistributionBatchModel.agency_id == group.agency_id,
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.document_type == document_type,
            DocumentDistributionBatchModel.status == "processing",
            DocumentDistributionBatchModel.id != batch_id,
        )
        .order_by(
            DocumentDistributionBatchModel.created_at.desc(),
            DocumentDistributionBatchModel.id.desc(),
        )
        .with_for_update()
    )
    remaining_processing_upload_ids = list(remaining_result.scalars().all())
    await AuditLogRepository(session).record(
        action="document_distribution_upload_aborted",
        entity_type="document_distribution_batch",
        entity_id=str(batch_id),
        agency_id=group.agency_id,
        user_id=actor.id,
        metadata={
            "group_id": str(group_id),
            "document_type": document_type,
            "deleted_document_count": len(documents),
            "deleted_chunk_count": len(receipts),
            "deleted_storage_object_count": len(delete_storage_keys),
            "remaining_processing_upload_count": len(remaining_processing_upload_ids),
        },
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        raise

    storage_cleanup_pending = False
    for cleanup_job in cleanup_jobs:
        try:
            cleanup_result = await process_storage_cleanup_job(cleanup_job.id)
            if cleanup_result is None or not cleanup_result.completed:
                storage_cleanup_pending = True
        except Exception as exc:
            storage_cleanup_pending = True
            logger.warning(
                "document_distribution_abort_cleanup_deferred",
                batch_id=str(batch_id),
                group_id=str(group_id),
                document_type=document_type,
                cleanup_job_id=str(cleanup_job.id),
                object_count=cleanup_job.object_count,
                error_type=type(exc).__name__,
            )

    return AbortDocumentUploadResponse(
        batch_id=batch_id,
        deleted_document_count=len(documents),
        deleted_chunk_count=len(receipts),
        deleted_storage_object_count=len(delete_storage_keys),
        storage_cleanup_pending=storage_cleanup_pending,
        remaining_processing_upload_ids=remaining_processing_upload_ids,
    )
