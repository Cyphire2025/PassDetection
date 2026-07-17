"""Queue re-extraction for an existing stored passport image."""

from __future__ import annotations

import uuid

from app.application.dtos.passport_dtos import (
    PassportSubmissionOutputDTO,
    passport_submission_output_from_entity,
)
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.exceptions.exceptions import EntityNotFoundError, ValidationError
from app.domain.repositories.interfaces import IPassportSubmissionRepository
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.processing.job_state import ProcessingJobStatus

logger = get_logger(__name__)


class ReextractPassportSubmissionUseCase:
    """Schedule extraction without reading or uploading the image in the request."""

    def __init__(
        self,
        passport_repo: IPassportSubmissionRepository,
        processing_job_repo: PassportProcessingJobRepository,
    ) -> None:
        self._passport_repo = passport_repo
        self._processing_job_repo = processing_job_repo

    async def execute(self, submission_id: uuid.UUID) -> PassportSubmissionOutputDTO:
        submission = await self._passport_repo.get_by_id_for_update(submission_id)
        if not submission:
            raise EntityNotFoundError("PassportSubmission", submission_id)
        if not submission.image_s3_key or submission.image_s3_key.startswith("excel-imports/"):
            raise ValidationError(
                "Upload a passport front image before running re-extraction.",
                field="image_s3_key",
            )

        active_job = await self._processing_job_repo.active_for_submission(
            submission.id,
            extraction_revision=submission.extraction_revision,
        )
        if active_job:
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
        logger.info(
            "passport_reextraction_queued",
            submission_id=str(submission.id),
            job_id=str(job.id),
            group_id=str(submission.group_id),
            agency_id=str(submission.agency_id),
        )
        return passport_submission_output_from_entity(submission, job=job)
