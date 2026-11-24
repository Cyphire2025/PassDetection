"""Project the committed distribution upload into the existing review response."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import PassportSubmission
from app.infrastructure.documents.distribution_ingestion import (
    TravelDocumentIngestionResult,
)
from app.presentation.api.v1.document_chunk_uploads import (
    DocumentChunkMetadata,
)
from app.presentation.api.v1.routes.document_distribution_queries import (
    _all_group_documents,
)
from app.presentation.api.v1.routes.document_distribution_responses import _batch_response
from app.presentation.api.v1.routes.document_distribution_shared import (
    _processing_batch_response,
)
from app.presentation.api.v1.schemas.document_distribution_schemas import (
    DocumentBatchResponse,
    RejectedDocumentResponse,
)


async def completed_distribution_upload_response(
    *,
    session: AsyncSession,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    document_type: str,
    passengers: list[PassportSubmission],
    ingestion: TravelDocumentIngestionResult,
    chunk_metadata: DocumentChunkMetadata | None,
) -> DocumentBatchResponse:
    if ingestion.batch.status == "processing":
        return _processing_batch_response(ingestion.batch)
    documents = await _all_group_documents(
        session,
        group_id=group_id,
        agency_id=agency_id,
        document_type=document_type,
    )
    return await _batch_response(
        session=session,
        group_id=group_id,
        agency_id=agency_id,
        document_type=document_type,
        passengers=passengers,
        batch=ingestion.batch,
        documents=documents,
        rejected_documents=(
            [
                RejectedDocumentResponse(
                    filename=item.filename,
                    detected_type=item.detected_type,
                    reason=item.reason,
                )
                for item in ingestion.rejected
            ]
            if chunk_metadata is None
            else None
        ),
    )
