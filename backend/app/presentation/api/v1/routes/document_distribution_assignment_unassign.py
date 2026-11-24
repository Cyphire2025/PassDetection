"""Document assignment removal with saved-file retention."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import propagate_mobile_passenger_change
from app.domain.entities.entities import User
from app.domain.value_objects.travel_document_taxonomy import DOCUMENT_TYPES
from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentWhatsAppDeliveryModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.document_approval_provenance import (
    preserve_document_type_approval,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.routes.document_distribution_assignment_review import (
    _current_assignment_batch_response,
)
from app.presentation.api.v1.routes.document_distribution_queries import (
    _refresh_distribution_batches,
)
from app.presentation.api.v1.routes.document_distribution_scope import (
    _get_authorized_group,
    _group_passengers,
)
from app.presentation.api.v1.routes.document_distribution_shared import (
    DOCUMENT_DELIVERY_STORAGE_REQUIRED_STATUSES,
)
from app.presentation.api.v1.routes.document_distribution_storage import (
    _released_document_passenger_ids,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DeleteDistributionDocumentsRequest,
    DocumentBatchResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.post(
    "/groups/{group_id}/{document_type}/documents/unassign",
    response_model=DocumentBatchResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def unassign_distribution_documents(
    group_id: uuid.UUID,
    document_type: str,
    payload: DeleteDistributionDocumentsRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> DocumentBatchResponse:
    if document_type not in DOCUMENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported document type"
        )
    group = await _get_authorized_group(group_id, current_user=current_user, session=session)
    passengers = await _group_passengers(group_id, current_user=current_user, session=session)
    document_ids = list(dict.fromkeys(payload.document_ids))
    if not document_ids:
        return await _current_assignment_batch_response(
            session=session,
            group_id=group_id,
            group=group,
            document_type=document_type,
            passengers=passengers,
        )
    await session.execute(
        select(DocumentDistributionBatchModel.id)
        .where(
            DocumentDistributionBatchModel.group_id == group_id,
            DocumentDistributionBatchModel.agency_id == group.agency_id,
            DocumentDistributionBatchModel.document_type == document_type,
        )
        .order_by(DocumentDistributionBatchModel.id)
        .with_for_update()
    )
    documents_result = await session.execute(
        select(DistributedDocumentModel)
        .where(
            DistributedDocumentModel.id.in_(document_ids),
            DistributedDocumentModel.group_id == group_id,
            DistributedDocumentModel.agency_id == group.agency_id,
            DistributedDocumentModel.document_type == document_type,
            DistributedDocumentModel.passenger_id.is_not(None),
            DistributedDocumentModel.match_status != "superseded",
        )
        .with_for_update()
    )
    documents_to_unassign = list(documents_result.scalars().all())
    if not documents_to_unassign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No assigned documents were found"
        )
    released_passenger_ids = await _released_document_passenger_ids(
        session,
        agency_id=group.agency_id,
        group_id=group_id,
        document_ids=[document.id for document in documents_to_unassign],
    )
    active_delivery_result = await session.execute(
        select(DocumentWhatsAppDeliveryModel.id)
        .where(
            DocumentWhatsAppDeliveryModel.distributed_document_id.in_(
                [document.id for document in documents_to_unassign]
            ),
            DocumentWhatsAppDeliveryModel.agency_id == group.agency_id,
            DocumentWhatsAppDeliveryModel.group_id == group_id,
            DocumentWhatsAppDeliveryModel.status.in_(DOCUMENT_DELIVERY_STORAGE_REQUIRED_STATUSES),
        )
        .with_for_update()
        .limit(1)
    )
    if active_delivery_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A selected document is currently being sent through WhatsApp. "
                "Wait for delivery processing to finish before removing its assignment."
            ),
        )
    affected_batch_ids = {document.batch_id for document in documents_to_unassign}
    now = datetime.now(tz=UTC)
    for document in documents_to_unassign:
        document.passenger_id = None
        document.match_status = "needs_review"
        document.match_confidence = 0.0
        document.match_reason = preserve_document_type_approval(
            document.match_reason, "Assignment removed manually; saved PDF retained for review"
        )
        document.updated_at = now
    await session.flush()
    await _refresh_distribution_batches(
        session,
        batch_ids=affected_batch_ids,
        agency_id=group.agency_id,
        group_id=group_id,
        now=now,
    )
    if released_passenger_ids:
        await propagate_mobile_passenger_change(
            session,
            agency_id=group.agency_id,
            group_id=group_id,
            passenger_submission_ids=released_passenger_ids,
            actor_user_id=current_user.id,
            operation="delete",
            change_kind="documents",
            reconcile_identities=False,
        )
    await AuditLogRepository(session).record(
        action="document_distribution_unassigned",
        entity_type="document_distribution_batch",
        entity_id=str(group_id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "group_id": str(group_id),
            "document_type": document_type,
            "unassigned_count": len(documents_to_unassign),
            "saved_files_retained": True,
        },
    )
    await session.commit()
    return await _current_assignment_batch_response(
        session=session,
        group_id=group_id,
        group=group,
        document_type=document_type,
        passengers=passengers,
    )


unassign_distribution_documents.__module__ = (
    "app.presentation.api.v1.routes.document_distribution_assignments"
)
