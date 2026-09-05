"""Document distribution: save."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import DocumentDistributionBatchModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.routes.document_distribution_scope import (
    _get_authorized_group,
    _get_visible_document_batch,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import SaveDocumentBatchResponse
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.post(
    "/batches/{batch_id}/save",
    response_model=SaveDocumentBatchResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def save_batch(
    batch_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> SaveDocumentBatchResponse:
    batch = await _get_visible_document_batch(
        session,
        batch_id=batch_id,
        current_user=current_user,
    )
    if not batch:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Document batch was not found"
        )
    await _get_authorized_group(batch.group_id, current_user=current_user, session=session)
    now = datetime.now(tz=UTC)
    group_batches_result = await session.execute(
        select(DocumentDistributionBatchModel)
        .where(
            DocumentDistributionBatchModel.group_id == batch.group_id,
            DocumentDistributionBatchModel.agency_id == batch.agency_id,
            DocumentDistributionBatchModel.document_type == batch.document_type,
        )
        .order_by(DocumentDistributionBatchModel.id)
        .with_for_update()
    )
    group_batches = list(group_batches_result.scalars().all())
    if any(item.status == "processing" for item in group_batches):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Wait for the document upload to finish before saving the list",
        )
    saved_batches = [item for item in group_batches if item.status != "saved"]
    for pending_batch in saved_batches:
        pending_batch.status = "saved"
        pending_batch.saved_at = now
        pending_batch.updated_at = now
    await AuditLogRepository(session).record(
        action="document_distribution_saved",
        entity_type="document_distribution_batch",
        entity_id=str(batch.id),
        agency_id=batch.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "group_id": str(batch.group_id),
            "document_type": batch.document_type,
            "saved_batch_count": len(saved_batches),
        },
    )
    await session.commit()
    return SaveDocumentBatchResponse(batch_id=batch.id, status=batch.status, saved_at=now)
