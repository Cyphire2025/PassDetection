"""Process a passport submission in a background worker."""

from __future__ import annotations

import mimetypes
import uuid

from app.application.interfaces.passport_extraction import IPassportExtractionService
from app.application.interfaces.passport_verification import IPassportVerificationService
from app.application.use_cases.passports.passport_ai_verification import verify_passport_fields
from app.core.logging.logger import get_logger
from app.domain.entities.entities import PassportProcessingStatus
from app.domain.exceptions.exceptions import PassDetectionError
from app.domain.repositories.interfaces import (
    IObjectStorageRepository,
    IPassportSubmissionRepository,
)
from app.infrastructure.ocr.passport_back_extraction_service import (
    PassportBackPageExtractionService,
)
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.processing.job_state import ProcessingJobStatus

logger = get_logger(__name__)


class ProcessingRetryRequested(Exception):
    """Raised when the task should be retried by the queue backend."""


class ProcessPassportSubmissionJobUseCase:
    def __init__(
        self,
        *,
        passport_repo: IPassportSubmissionRepository,
        storage_repo: IObjectStorageRepository,
        extraction_service: IPassportExtractionService,
        job_repo: PassportProcessingJobRepository,
        back_extraction_service: PassportBackPageExtractionService | None = None,
        allow_retry: bool = True,
        verification_service: IPassportVerificationService | None = None,
    ) -> None:
        self._passport_repo = passport_repo
        self._storage_repo = storage_repo
        self._extraction_service = extraction_service
        self._job_repo = job_repo
        self._back_extraction_service = back_extraction_service or PassportBackPageExtractionService()
        self._allow_retry = allow_retry
        self._verification_service = verification_service

    async def execute(self, *, submission_id: uuid.UUID, job_id: uuid.UUID) -> None:
        job = await self._job_repo.mark_running(job_id, stage="starting")
        if job.status == ProcessingJobStatus.CANCELLED:
            logger.info("passport_processing_job_cancelled_before_start", job_id=str(job_id))
            return

        submission = await self._passport_repo.get_by_id(submission_id)
        if not submission:
            await self._job_repo.mark_dead_letter(job_id, "Passport submission was not found")
            return

        if submission.status != PassportProcessingStatus.PROCESSING:
            submission.mark_processing()
            await self._passport_repo.update(submission)

        try:
            await self._job_repo.update_progress(job_id, progress=0.15, stage="downloading_image")
            file_content = await self._storage_repo.get_file(submission.image_s3_key)
            if await self._cancel_if_requested(job_id, submission):
                return

            await self._job_repo.update_progress(job_id, progress=0.35, stage="extracting_passport_fields")
            extraction = await self._extraction_service.extract(
                file_content,
                filename=submission.image_s3_key.rsplit("/", 1)[-1],
                content_type=self._guess_content_type(submission.image_s3_key),
            )
            if await self._cancel_if_requested(job_id, submission):
                return

            await self._job_repo.update_progress(job_id, progress=0.70, stage="verifying_passport_fields")
            extracted_fields = await verify_passport_fields(
                self._verification_service,
                image_content=file_content,
                content_type=self._guess_content_type(submission.image_s3_key),
                extracted_fields=extraction.extracted_fields,
            )
            await self._job_repo.update_progress(job_id, progress=0.85, stage="saving_extraction_result")
            if submission.passport_back_s3_key:
                back_content = await self._storage_repo.get_file(submission.passport_back_s3_key)
                back_result = await self._back_extraction_service.extract(back_content)
                if back_result.fields.get("raw_text"):
                    extracted_fields["passport_back"] = back_result.fields
            submission.mark_review_required(
                extracted_fields=extracted_fields,
                confidence=extraction.overall_confidence,
                confidence_score=extraction.confidence_score,
                mrz_raw=extraction.mrz_raw,
            )
            await self._passport_repo.update(submission)
            await self._job_repo.mark_succeeded(job_id)
            logger.info(
                "passport_processing_job_succeeded",
                job_id=str(job_id),
                submission_id=str(submission.id),
                confidence=extraction.overall_confidence,
            )
        except PassDetectionError as exc:
            await self._handle_failure(job_id, submission, exc.message)
        except Exception as exc:
            logger.exception(
                "passport_processing_job_unexpected_failure",
                job_id=str(job_id),
                submission_id=str(submission_id),
                error=str(exc),
            )
            await self._handle_failure(job_id, submission, "Automatic passport extraction failed")

    async def _handle_failure(self, job_id: uuid.UUID, submission, message: str) -> None:  # type: ignore[no-untyped-def]
        latest = await self._job_repo.get(job_id)
        if self._allow_retry and latest and latest.attempts < latest.max_attempts:
            await self._job_repo.mark_retryable_failure(job_id, message)
            raise ProcessingRetryRequested(message)

        submission.mark_failed(message)
        await self._passport_repo.update(submission)
        await self._job_repo.mark_dead_letter(job_id, message)
        logger.warning(
            "passport_processing_job_dead_lettered",
            job_id=str(job_id),
            submission_id=str(submission.id),
            error=message,
        )

    async def _cancel_if_requested(self, job_id: uuid.UUID, submission) -> bool:  # type: ignore[no-untyped-def]
        latest = await self._job_repo.get(job_id)
        if not latest or not latest.cancel_requested:
            return False
        submission.mark_failed("Processing was cancelled")
        await self._passport_repo.update(submission)
        await self._job_repo.mark_cancelled(job_id, "Processing was cancelled")
        logger.info(
            "passport_processing_job_cancelled",
            job_id=str(job_id),
            submission_id=str(submission.id),
        )
        return True

    def _guess_content_type(self, key: str) -> str:
        return mimetypes.guess_type(key)[0] or "image/jpeg"
