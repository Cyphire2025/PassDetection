"""
Re-extract Passport Submission Use Case
======================================
"""

from __future__ import annotations

import uuid

from app.application.dtos.passport_dtos import PassportSubmissionOutputDTO
from app.application.interfaces.passport_extraction import IPassportExtractionService
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.domain.repositories.interfaces import IObjectStorageRepository, IPassportSubmissionRepository
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository

logger = get_logger(__name__)


class ReextractPassportSubmissionUseCase:
    """Reruns extraction against the original stored passport image."""

    def __init__(
        self,
        passport_repo: IPassportSubmissionRepository,
        storage_repo: IObjectStorageRepository | None = None,
        extraction_service: IPassportExtractionService | None = None,
        processing_job_repo: PassportProcessingJobRepository | None = None,
    ) -> None:
        self._passport_repo = passport_repo
        self._storage_repo = storage_repo
        self._extraction_service = extraction_service
        self._processing_job_repo = processing_job_repo

    async def execute(self, submission_id: uuid.UUID) -> PassportSubmissionOutputDTO:
        submission = await self._passport_repo.get_by_id(submission_id)
        if not submission:
            raise EntityNotFoundError("PassportSubmission", submission_id)

        submission.mark_processing()
        await self._passport_repo.update(submission)

        job = None
        if self._processing_job_repo is not None:
            job = await self._processing_job_repo.create(
                submission_id=submission.id,
                max_attempts=get_settings().processing_job_max_attempts,
            )
            logger.info(
                "passport_reextraction_queued",
                submission_id=str(submission.id),
                job_id=str(job.id),
                group_id=str(submission.group_id),
                agency_id=str(submission.agency_id),
            )

        return self._to_dto(submission, job=job)

    def _to_dto(self, submission, job=None) -> PassportSubmissionOutputDTO:  # type: ignore[no-untyped-def]
        return PassportSubmissionOutputDTO(
            id=submission.id,
            group_id=submission.group_id,
            agency_id=submission.agency_id,
            client_name=submission.client_name,
            client_email=submission.client_email,
            client_phone=submission.client_phone,
            image_s3_key=submission.image_s3_key,
            thumbnail_s3_key=submission.thumbnail_s3_key,
            status=submission.status.value,
            created_at=submission.created_at,
            updated_at=submission.updated_at,
            extracted_fields=submission.extracted_fields,
            confirmed_fields=submission.confirmed_fields,
            overall_confidence=submission.overall_confidence,
            confidence_score=submission.confidence_score,
            mrz_raw=submission.mrz_raw,
            error_message=submission.error_message,
            client_reviewed_at=submission.client_reviewed_at,
            confirmed_at=submission.confirmed_at,
            processing_job_id=job.id if job else None,
            processing_job_status=job.status.value if job else None,
            processing_progress=job.progress if job else None,
            processing_stage=job.current_stage if job else None,
        )
