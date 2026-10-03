"""Project retained ingestion rejections without creating file capabilities."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import DocumentUploadChunkModel
from app.presentation.api.v1.schemas.document_distribution_schemas import RejectedDocumentResponse


async def retained_batch_rejections(session: AsyncSession, *, upload_id: UUID,
    agency_id: UUID, group_id: UUID, document_type: str) -> list[RejectedDocumentResponse]:
    result = await session.execute(select(DocumentUploadChunkModel.rejected_documents).where(
        DocumentUploadChunkModel.upload_id == upload_id,
        DocumentUploadChunkModel.agency_id == agency_id,
        DocumentUploadChunkModel.workflow == "distribution",
        DocumentUploadChunkModel.group_id == group_id,
        DocumentUploadChunkModel.document_type == document_type,
    ).order_by(DocumentUploadChunkModel.chunk_index.asc()))
    rejected = []
    for chunk in result.scalars().all():
        if not isinstance(chunk, list):
            continue
        for item in chunk:
            if not isinstance(item, dict) or not all(isinstance(item.get(key), str)
                                                     for key in ("filename", "detected_type", "reason")):
                continue
            rejected.append(RejectedDocumentResponse(filename=item["filename"],
                detected_type=item["detected_type"], reason=item["reason"]))
    return rejected
