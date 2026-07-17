"""Process one persisted passport front image in a retryable background job."""

from __future__ import annotations

import asyncio
import mimetypes
import uuid

from app.application.interfaces.passport_extraction import IPassportExtractionService
from app.application.interfaces.passport_verification import IPassportVerificationService
from app.application.use_cases.passports.passport_ai_verification import verify_passport_fields
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.domain.exceptions.exceptions import PassDetectionError, StorageError
from app.domain.repositories.interfaces import (
    IObjectStorageRepository,
    IPassportSubmissionRepository,
)
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.processing.job_state import ProcessingJobStatus

logger = get_logger(__name__)

PUBLIC_EXTRACTION_FAILURE = (
    "Some passport fields could not be read automatically. "
    "Please enter the missing details manually."
)


class ProcessingRetryRequested(Exception):
    """Raised when the queue backend should retry a transient extraction failure."""


class ProcessPassportSubmissionJobUseCase:
    def __init__(
        self,
        *,
        passport_repo: IPassportSubmissionRepository,
        storage_repo: IObjectStorageRepository,
        extraction_service: IPassportExtractionService,
        job_repo: PassportProcessingJobRepository,
        allow_retry: bool = True,
        verification_service: IPassportVerificationService | None = None,
    ) -> None:
        self._passport_repo = passport_repo
        self._storage_repo = storage_repo
        self._extraction_service = extraction_service
        self._job_repo = job_repo
        self._allow_retry = allow_retry
        self._verification_service = verification_service

    async def execute(self, *, submission_id: uuid.UUID, job_id: uuid.UUID) -> None:
        job, claimed = await self._job_repo.claim_running(job_id, stage="starting")
        if job is None:
            return
        if not claimed:
            if job.status == ProcessingJobStatus.RUNNING:
                raise ProcessingRetryRequested(
                    "Another worker is still processing this passport"
                )
            logger.info(
                "passport_processing_job_duplicate_delivery_ignored",
                job_id=str(job_id),
                status=job.status.value,
            )
            return
        await self._job_repo.checkpoint()
        if job.status in {
            ProcessingJobStatus.CANCELLED,
            ProcessingJobStatus.SUCCEEDED,
            ProcessingJobStatus.DEAD_LETTER,
            ProcessingJobStatus.FAILED,
        }:
            logger.info(
                "passport_processing_job_not_runnable",
                job_id=str(job_id),
                status=job.status.value,
            )
            return
        if job.submission_id != submission_id:
            await self._job_repo.mark_dead_letter(job_id, "Processing job target mismatch")
            return

        submission = await self._passport_repo.get_by_id(submission_id)
        if not submission:
            await self._job_repo.mark_dead_letter(job_id, "Passport submission was not found")
            return
        if submission.extraction_revision != job.extraction_revision:
            await self._job_repo.mark_cancelled(job_id, "Superseded by newer passport changes")
            logger.info(
                "passport_processing_job_stale_before_start",
                job_id=str(job_id),
                submission_id=str(submission_id),
            )
            return

        try:
            async with asyncio.timeout(get_settings().processing_job_timeout_seconds):
                await self._job_repo.update_progress(
                    job_id,
                    progress=0.15,
                    stage="downloading_image",
                )
                await self._job_repo.checkpoint()
                file_content = await self._storage_repo.get_file(submission.image_s3_key)
                if await self._cancel_if_requested(job_id, submission_id, job.extraction_revision):
                    return

                await self._job_repo.update_progress(
                    job_id,
                    progress=0.35,
                    stage="extracting_passport_fields",
                )
                await self._job_repo.checkpoint()
                content_type = self._guess_content_type(submission.image_s3_key)
                extraction = await self._extraction_service.extract(
                    file_content,
                    filename=submission.image_s3_key.rsplit("/", 1)[-1],
                    content_type=content_type,
                )
                if await self._cancel_if_requested(job_id, submission_id, job.extraction_revision):
                    return

                await self._job_repo.update_progress(
                    job_id,
                    progress=0.70,
                    stage="verifying_passport_fields",
                )
                await self._job_repo.checkpoint()
                extracted_fields = await verify_passport_fields(
                    self._verification_service,
                    image_content=file_content,
                    content_type=content_type,
                    extracted_fields=extraction.extracted_fields,
                )
                await self._job_repo.update_progress(
                    job_id,
                    progress=0.90,
                    stage="saving_extraction_result",
                )
                await self._job_repo.checkpoint()
                applied = await self._passport_repo.apply_extraction_result(
                    submission_id=submission.id,
                    expected_revision=job.extraction_revision,
                    extracted_fields=extracted_fields,
                    confidence=extraction.overall_confidence,
                    confidence_score=extraction.confidence_score,
                    mrz_raw=extraction.mrz_raw,
                )
                if not applied:
                    await self._job_repo.mark_cancelled(
                        job_id,
                        "Superseded by newer passport changes",
                    )
                    logger.info(
                        "passport_processing_job_stale_result_discarded",
                        job_id=str(job_id),
                        submission_id=str(submission.id),
                    )
                    return

            await self._job_repo.mark_succeeded(job_id)
            logger.info(
                "passport_processing_job_succeeded",
                job_id=str(job_id),
                submission_id=str(submission.id),
                confidence=extraction.overall_confidence,
            )
        except TimeoutError:
            logger.warning(
                "passport_processing_job_timed_out",
                job_id=str(job_id),
                submission_id=str(submission_id),
            )
            await self._handle_failure(job_id, submission_id, job.extraction_revision)
        except StorageError as exc:
            logger.warning(
                "passport_processing_storage_read_failure",
                job_id=str(job_id),
                submission_id=str(submission_id),
                error_type=type(exc).__name__,
            )
            await self._handle_failure(job_id, submission_id, job.extraction_revision)
        except PassDetectionError as exc:
            logger.warning(
                "passport_processing_job_provider_failure",
                job_id=str(job_id),
                submission_id=str(submission_id),
                error_type=type(exc).__name__,
            )
            await self._handle_failure(job_id, submission_id, job.extraction_revision)
        except Exception as exc:
            logger.exception(
                "passport_processing_job_unexpected_failure",
                job_id=str(job_id),
                submission_id=str(submission_id),
                error_type=type(exc).__name__,
            )
            await self._handle_failure(job_id, submission_id, job.extraction_revision)

    async def _handle_failure(
        self,
        job_id: uuid.UUID,
        submission_id: uuid.UUID,
        extraction_revision: int,
    ) -> None:
        latest = await self._job_repo.get(job_id)
        if self._allow_retry and latest and latest.attempts < latest.max_attempts:
            await self._job_repo.mark_retryable_failure(
                job_id,
                "Automatic extraction will be retried",
            )
            raise ProcessingRetryRequested("Automatic extraction will be retried")

        applied = await self._passport_repo.apply_extraction_failure(
            submission_id=submission_id,
            expected_revision=extraction_revision,
            public_message=PUBLIC_EXTRACTION_FAILURE,
        )
        if not applied:
            await self._job_repo.mark_cancelled(job_id, "Superseded by newer passport changes")
            return
        await self._job_repo.mark_dead_letter(job_id, PUBLIC_EXTRACTION_FAILURE)
        logger.warning(
            "passport_processing_job_finished_for_manual_review",
            job_id=str(job_id),
            submission_id=str(submission_id),
        )

    async def _cancel_if_requested(
        self,
        job_id: uuid.UUID,
        submission_id: uuid.UUID,
        extraction_revision: int,
    ) -> bool:
        latest = await self._job_repo.get(job_id)
        if not latest or not latest.cancel_requested:
            return False
        await self._passport_repo.apply_extraction_failure(
            submission_id=submission_id,
            expected_revision=extraction_revision,
            public_message=PUBLIC_EXTRACTION_FAILURE,
        )
        await self._job_repo.mark_cancelled(job_id, "Processing was cancelled")
        logger.info(
            "passport_processing_job_cancelled",
            job_id=str(job_id),
            submission_id=str(submission_id),
        )
        return True

    @staticmethod
    def _guess_content_type(key: str) -> str:
        return mimetypes.guess_type(key)[0] or "image/jpeg"
