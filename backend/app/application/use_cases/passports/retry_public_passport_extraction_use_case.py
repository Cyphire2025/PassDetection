"""Queue OCR again for an already-persisted public passport image."""

from __future__ import annotations

import uuid

from app.application.dtos.passport_dtos import (
    PassportSubmissionOutputDTO,
    passport_submission_output_from_entity,
)
from app.application.security.public_upload_capability import require_active_public_upload
from app.core.config.settings import get_settings
from app.domain.entities.entities import PassportProcessingStatus
from app.domain.exceptions.exceptions import EntityNotFoundError, ValidationError
from app.domain.repositories.interfaces import (
    IClientGroupRepository,
    IPassportSubmissionRepository,
)
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.processing.job_state import ProcessingJobStatus


class RetryPublicPassportExtractionUseCase:
    """Create one retryable extraction job without re-uploading either page."""

    def __init__(
        self,
        *,
        passport_repo: IPassportSubmissionRepository,
        client_group_repo: IClientGroupRepository,
        processing_job_repo: PassportProcessingJobRepository,
    ) -> None:
        self._passport_repo = passport_repo
        self._client_group_repo = client_group_repo
        self._processing_job_repo = processing_job_repo

    async def execute(
        self,
        *,
        token: str,
        submission_id: uuid.UUID,
    ) -> PassportSubmissionOutputDTO:
        group = await self._client_group_repo.get_by_token(token)
        if not group:
            raise EntityNotFoundError("ClientGroup", token)
        require_active_public_upload(group)

        submission = await self._passport_repo.get_by_id_for_update(submission_id)
        if not submission or submission.group_id != group.id:
            raise EntityNotFoundError("PassportSubmission", submission_id)
        if submission.status in {
            PassportProcessingStatus.CLIENT_SUBMITTED,
            PassportProcessingStatus.CONFIRMED,
            PassportProcessingStatus.SUBMITTED,
            PassportProcessingStatus.AI_APPROVED,
            PassportProcessingStatus.NEEDS_REVIEW,
            PassportProcessingStatus.STAFF_APPROVED,
        }:
            raise ValidationError(
                "Passport details were already submitted.",
                field="submission_id",
            )

        active_job = await self._processing_job_repo.active_for_submission(
            submission.id,
            extraction_revision=submission.extraction_revision,
        )
        if active_job and active_job.status in {
            ProcessingJobStatus.QUEUED,
            ProcessingJobStatus.RUNNING,
        }:
            return passport_submission_output_from_entity(
                submission,
                job=active_job if active_job.status == ProcessingJobStatus.QUEUED else None,
            )

        extraction_revision = submission.mark_processing()
        await self._passport_repo.update(submission)
        job = await self._processing_job_repo.create(
            submission_id=submission.id,
            extraction_revision=extraction_revision,
            max_attempts=get_settings().processing_job_max_attempts,
        )
        return passport_submission_output_from_entity(submission, job=job)
