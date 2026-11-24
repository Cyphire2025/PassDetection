"""Read the existing current review for an assignment action."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import PassportSubmission
from app.infrastructure.database.models import ClientGroupModel
from app.presentation.api.v1.routes.document_distribution_queries import (
    _all_group_documents,
    _latest_document_batch,
)
from app.presentation.api.v1.routes.document_distribution_responses import _batch_response
from app.presentation.api.v1.schemas.document_distribution_schemas import DocumentBatchResponse


async def _current_assignment_batch_response(
    *,
    session: AsyncSession,
    group_id: uuid.UUID,
    group: ClientGroupModel,
    document_type: str,
    passengers: list[PassportSubmission],
) -> DocumentBatchResponse:
    """Read the existing current review after a no-op or committed assignment action."""
    batch = await _latest_document_batch(
        session,
        group_id=group_id,
        agency_id=group.agency_id,
        document_type=document_type,
    )
    documents = await _all_group_documents(
        session,
        group_id=group_id,
        agency_id=group.agency_id,
        document_type=document_type,
    )
    return await _batch_response(
        session=session,
        group_id=group_id,
        agency_id=group.agency_id,
        document_type=document_type,
        passengers=passengers,
        batch=batch,
        documents=documents,
    )
