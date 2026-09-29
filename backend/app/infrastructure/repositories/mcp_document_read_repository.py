"""Bounded tenant-consistent document batches, metadata and processing jobs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    PassportProcessingJobModel,
    PassportSubmissionModel,
)
from app.infrastructure.repositories.operational_roster import operational_roster_member


class MCPDocumentReadRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _page(self, statement: Any, model: Any, cutoff: datetime,
                    after: tuple[datetime, uuid.UUID] | None, size: int) -> list[dict[str, Any]]:
        statement = statement.where(model.created_at <= cutoff)
        if after:
            statement = statement.where(or_(model.created_at < after[0],
                                            and_(model.created_at == after[0], model.id < after[1])))
        result = await self.session.execute(statement.order_by(model.created_at.desc(), model.id.desc()).limit(size + 1))
        return [dict(row) for row in result.mappings()]

    async def documents(self, *, group_id: uuid.UUID, agency_id: uuid.UUID, document_type: str | None,
                        include_extracted_identifiers: bool, cutoff: datetime,
                        after: tuple[datetime, uuid.UUID] | None, size: int) -> list[dict[str, Any]]:
        document, passport = DistributedDocumentModel, PassportSubmissionModel
        operational = select(passport.id).where(passport.id == document.passenger_id,
            passport.group_id == document.group_id, passport.agency_id == document.agency_id,
            passport.status.in_(OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES), operational_roster_member()).correlate(document).exists()
        fields = [document.id, document.batch_id, document.passenger_id, document.document_type,
                  document.original_filename, document.content_type, document.detected_type,
                  document.match_status, document.match_confidence, document.match_reason,
                  document.created_at, document.updated_at, operational.label("assigned_to_operational_passenger")]
        if include_extracted_identifiers:
            fields.extend([document.extracted_name, document.extracted_passport_number, document.extracted_reference])
        statement = select(*fields).where(document.group_id == group_id, document.agency_id == agency_id)
        if document_type is not None:
            statement = statement.where(document.document_type == document_type)
        return await self._page(statement, document, cutoff, after, size)

    async def batches(self, *, group_id: uuid.UUID, agency_id: uuid.UUID, document_type: str | None,
                      cutoff: datetime, after: tuple[datetime, uuid.UUID] | None, size: int) -> list[dict[str, Any]]:
        model = DocumentDistributionBatchModel
        statement = select(model.id, model.document_type, model.status, model.uploaded_count,
                           model.rejected_count, model.matched_count, model.saved_at,
                           model.created_at, model.updated_at).where(model.group_id == group_id, model.agency_id == agency_id)
        if document_type is not None:
            statement = statement.where(model.document_type == document_type)
        return await self._page(statement, model, cutoff, after, size)

    async def processing_jobs(self, *, group_id: uuid.UUID, agency_id: uuid.UUID,
                              submission_id: uuid.UUID | None, status: str | None, cutoff: datetime,
                              after: tuple[datetime, uuid.UUID] | None, size: int) -> list[dict[str, Any]]:
        job, passport = PassportProcessingJobModel, PassportSubmissionModel
        statement = select(job.id, job.submission_id, job.status, job.extraction_revision,
            passport.extraction_revision.label("current_submission_revision"),
            (job.extraction_revision == passport.extraction_revision).label("is_current_revision"),
            job.progress, job.attempts, job.max_attempts, job.current_stage, job.cancel_requested,
            job.error_message.is_not(None).label("has_error"), job.created_at, job.updated_at,
            job.started_at, job.finished_at).join(passport, passport.id == job.submission_id).where(
                passport.group_id == group_id, passport.agency_id == agency_id)
        if submission_id is not None:
            statement = statement.where(job.submission_id == submission_id)
        if status is not None:
            statement = statement.where(job.status == status)
        return await self._page(statement, job, cutoff, after, size)
