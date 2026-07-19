"""Process one persisted passport front image in a retryable background job."""

from __future__ import annotations

import asyncio
import mimetypes
import uuid
from typing import Any

from app.application.interfaces.passport_extraction import (
    IPassportExtractionService,
    PassportExtractionResult,
)
from app.application.interfaces.passport_verification import IPassportVerificationService
from app.application.use_cases.passports.passport_ai_verification import verify_passport_fields
from app.core.config.settings import get_settings
from app.core.logging.logger import get_logger
from app.core.time_budget import TimeBudget
from app.domain.exceptions.exceptions import PassDetectionError, StorageError
from app.domain.repositories.interfaces import (
    IObjectStorageRepository,
    IPassportSubmissionRepository,
)
from app.domain.value_objects.passport_document_classification import (
    ACCEPTED_PASSPORT_DOCUMENT_STATUSES,
)
from app.infrastructure.observability.operational_events import (
    OperationalEvent,
    record_operational_event,
)
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.processing.job_state import ProcessingJobStatus

logger = get_logger(__name__)

PUBLIC_EXTRACTION_FAILURE = (
    "Some passport fields could not be read automatically. "
    "Please enter the missing details manually."
)
PUBLIC_DOCUMENT_VERIFICATION_UNAVAILABLE = (
    "We could not verify that this is a passport photo and details page right now. "
    "Your upload was saved; please try again in a moment."
)
MAX_FIRST_PASS_SECONDS = 45.0
MAX_GEMINI_SECONDS = 30.0
RESULT_SAVE_RESERVE_SECONDS = 2.0
DOCUMENT_CLASSIFICATION_FAILURE_MESSAGES: dict[str, str] = {
    "passport_cover": (
        "A passport cover was detected. Open the passport to the photo and "
        "details page, then scan again."
    ),
    "wrong_passport_page": (
        "This is not the passport photo and details page. Open that page and "
        "scan it again."
    ),
    "wrong_document": (
        "This image is not a passport photo and details page. Scan the correct "
        "passport page and try again."
    ),
    "document_low_quality": (
        "The passport page is not clear enough to read. Use good lighting, "
        "avoid glare, and scan it again."
    ),
    "document_unreadable": (
        "The passport page could not be read. Place the full photo and details "
        "page inside the guide and scan it again."
    ),
    "document_uncertain": (
        "This image could not be confirmed as a passport photo and details "
        "page. Check the page and scan it again."
    ),
}
HIGH_CONFIDENCE_WRONG_DOCUMENT_MESSAGES: dict[str, str] = {
    "aadhaar": (
        "This appears to be an Aadhaar Card. Scan the passport photo and "
        "details page and try again."
    ),
    "pan": (
        "This appears to be a PAN Card. Scan the passport photo and details "
        "page and try again."
    ),
}
HIGH_CONFIDENCE_DOCUMENT_NAME_THRESHOLD = 0.90
GEMINI_EXTRACTION_FIELDS: tuple[str, ...] = (
    "surname",
    "given_names",
    "passport_number",
    "nationality",
    "issuing_country",
    "date_of_birth",
    "date_of_issue",
    "date_of_expiry",
    "sex",
)


class ProcessingRetryRequested(Exception):
    """Raised when the queue backend should retry a transient extraction failure."""


class ProcessingJobBusy(RuntimeError):
    """Raised when another worker still owns the durable RUNNING claim."""

    def __init__(
        self,
        message: str = "Another worker is still processing this passport",
        *,
        retry_after_ms: int = 5_000,
    ) -> None:
        super().__init__(message)
        self.retry_after_ms = max(1, retry_after_ms)


class ProcessPassportSubmissionJobUseCase:
    def __init__(
        self,
        *,
        passport_repo: IPassportSubmissionRepository,
        storage_repo: IObjectStorageRepository,
        extraction_service: IPassportExtractionService | None,
        job_repo: PassportProcessingJobRepository,
        allow_retry: bool = True,
        verification_service: IPassportVerificationService | None = None,
    ) -> None:
        self._passport_repo = passport_repo
        self._storage_repo = storage_repo
        # Keep the local OCR/MRZ implementation dependency available for a
        # future opt-in fallback. The active first pass intentionally does not
        # invoke it: Gemini reads the persisted passport image directly.
        self._dormant_local_extraction_service = extraction_service
        self._job_repo = job_repo
        self._allow_retry = allow_retry
        self._verification_service = verification_service

    async def execute(self, *, submission_id: uuid.UUID, job_id: uuid.UUID) -> None:
        job, claimed = await self._job_repo.claim_running(job_id, stage="starting")
        if job is None:
            return
        if not claimed:
            if job.status == ProcessingJobStatus.RUNNING:
                raise ProcessingJobBusy(
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

        extraction_started = False
        try:
            settings = get_settings()
            job_timeout = min(
                float(settings.processing_job_timeout_seconds),
                MAX_FIRST_PASS_SECONDS,
            )
            budget = TimeBudget.start(job_timeout)
            async with asyncio.timeout(job_timeout):
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
                # Local OCR/MRZ is deliberately unwired for now. Its service,
                # implementation, and dependency injection remain in place so
                # it can be re-enabled later without reconstructing the stack.
                # await self._dormant_local_extraction_service.extract(...)
                await self._job_repo.update_progress(
                    job_id,
                    progress=0.70,
                    stage="verifying_passport_fields",
                )
                await self._job_repo.checkpoint()
                verification_timeout = min(
                    float(getattr(settings, "gemini_timeout_seconds", 30.0)),
                    MAX_GEMINI_SECONDS,
                    max(0.0, budget.remaining() - RESULT_SAVE_RESERVE_SECONDS),
                )
                extraction_started = True
                extracted_fields = await verify_passport_fields(
                    self._verification_service,
                    image_content=file_content,
                    content_type=content_type,
                    extracted_fields={},
                    timeout_seconds=verification_timeout,
                )
                extraction = self._gemini_extraction_result(extracted_fields)
                if await self._cancel_if_requested(
                    job_id,
                    submission_id,
                    job.extraction_revision,
                ):
                    return
                classification = self._safe_document_classification(
                    extracted_fields
                )
                classification_status = classification.get("status")
                if classification_status in DOCUMENT_CLASSIFICATION_FAILURE_MESSAGES:
                    record_operational_event(
                        OperationalEvent.DOCUMENT_CLASSIFICATION,
                        str(classification_status),
                    )
                    public_message = self._document_classification_failure_message(
                        classification
                    )
                    applied = await self._passport_repo.apply_extraction_failure(
                        submission_id=submission.id,
                        expected_revision=job.extraction_revision,
                        public_message=public_message,
                        diagnostics={"ai_verification": classification},
                    )
                    if not applied:
                        await self._job_repo.mark_cancelled(
                            job_id,
                            "Superseded by newer passport changes",
                        )
                        return
                    await self._job_repo.mark_dead_letter(
                        job_id,
                        public_message,
                    )
                    logger.warning(
                        "passport_document_classification_rejected",
                        job_id=str(job_id),
                        submission_id=str(submission.id),
                        status=classification_status,
                        document_class=classification.get("document_class"),
                        reason_code=classification.get("reason_code"),
                    )
                    return
                classification_available = classification.get("available") is True
                if (
                    classification_status not in ACCEPTED_PASSPORT_DOCUMENT_STATUSES
                    or not classification_available
                ):
                    record_operational_event(
                        OperationalEvent.DOCUMENT_CLASSIFICATION,
                        "provider_unavailable",
                    )
                    unavailable_diagnostics = classification or {
                        "status": "unavailable",
                        "available": False,
                    }
                    applied = await self._passport_repo.apply_extraction_failure(
                        submission_id=submission.id,
                        expected_revision=job.extraction_revision,
                        public_message=PUBLIC_DOCUMENT_VERIFICATION_UNAVAILABLE,
                        diagnostics={"ai_verification": unavailable_diagnostics},
                    )
                    if not applied:
                        await self._job_repo.mark_cancelled(
                            job_id,
                            "Superseded by newer passport changes",
                        )
                        return
                    await self._job_repo.mark_dead_letter(
                        job_id,
                        PUBLIC_DOCUMENT_VERIFICATION_UNAVAILABLE,
                    )
                    logger.warning(
                        "passport_document_classification_unavailable",
                        job_id=str(job_id),
                        submission_id=str(submission.id),
                        status=classification_status or "missing",
                    )
                    return
                record_operational_event(
                    OperationalEvent.DOCUMENT_CLASSIFICATION,
                    "accepted",
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
            await self._handle_failure(
                job_id,
                submission_id,
                job.extraction_revision,
                retry_allowed=not extraction_started,
            )
        except StorageError as exc:
            logger.warning(
                "passport_processing_storage_read_failure",
                job_id=str(job_id),
                submission_id=str(submission_id),
                error_type=type(exc).__name__,
            )
            await self._handle_failure(
                job_id,
                submission_id,
                job.extraction_revision,
                retry_allowed=not extraction_started,
            )
        except PassDetectionError as exc:
            logger.warning(
                "passport_processing_job_provider_failure",
                job_id=str(job_id),
                submission_id=str(submission_id),
                error_type=type(exc).__name__,
            )
            await self._handle_failure(
                job_id,
                submission_id,
                job.extraction_revision,
                retry_allowed=False,
            )
        except Exception as exc:
            logger.error(
                "passport_processing_job_unexpected_failure",
                job_id=str(job_id),
                submission_id=str(submission_id),
                error_type=type(exc).__name__,
            )
            await self._handle_failure(
                job_id,
                submission_id,
                job.extraction_revision,
                retry_allowed=False,
            )

    async def _handle_failure(
        self,
        job_id: uuid.UUID,
        submission_id: uuid.UUID,
        extraction_revision: int,
        *,
        retry_allowed: bool = True,
    ) -> None:
        latest = await self._job_repo.get(job_id)
        if (
            retry_allowed
            and self._allow_retry
            and latest
            and latest.attempts < latest.max_attempts
        ):
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

    @staticmethod
    def _safe_document_classification(
        extracted_fields: dict[str, Any],
    ) -> dict[str, object]:
        raw = extracted_fields.get("ai_verification")
        if not isinstance(raw, dict):
            return {}
        allowed_keys = {
            "status",
            "available",
            "model",
            "provider_status",
            "attempts",
            "duration_ms",
            "document_class",
            "page_type",
            "image_quality",
            "classification_confidence",
            "reason_code",
        }
        return {
            key: value
            for key, value in raw.items()
            if key in allowed_keys
            and isinstance(value, (str, int, float, bool, type(None)))
        }

    @staticmethod
    def _document_classification_failure_message(
        classification: dict[str, object],
    ) -> str:
        raw_status = classification.get("status")
        status = raw_status if isinstance(raw_status, str) else "document_uncertain"
        fallback = DOCUMENT_CLASSIFICATION_FAILURE_MESSAGES.get(
            status,
            DOCUMENT_CLASSIFICATION_FAILURE_MESSAGES["document_uncertain"],
        )
        if status != "wrong_document":
            return fallback
        document_class = classification.get("document_class")
        confidence = classification.get("classification_confidence")
        if (
            isinstance(document_class, str)
            and document_class in HIGH_CONFIDENCE_WRONG_DOCUMENT_MESSAGES
            and isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and float(confidence) >= HIGH_CONFIDENCE_DOCUMENT_NAME_THRESHOLD
        ):
            return HIGH_CONFIDENCE_WRONG_DOCUMENT_MESSAGES[document_class]
        return fallback

    @staticmethod
    def _gemini_extraction_result(
        extracted_fields: dict[str, Any],
    ) -> PassportExtractionResult:
        raw_metadata = extracted_fields.get("ai_verification")
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        raw_field_confidences = metadata.get("field_confidences")
        field_confidences = (
            raw_field_confidences
            if isinstance(raw_field_confidences, dict)
            else {}
        )
        raw_absent_fields = metadata.get("absent_fields")
        absent_fields = {
            field
            for field in (
                raw_absent_fields
                if isinstance(raw_absent_fields, list)
                else []
            )
            if field == "surname"
        }
        bounded_confidences: dict[str, float] = {}
        for field in GEMINI_EXTRACTION_FIELDS:
            raw_confidence = field_confidences.get(field)
            if (
                isinstance(raw_confidence, (int, float))
                and not isinstance(raw_confidence, bool)
                and 0.0 <= float(raw_confidence) <= 1.0
                and (
                    extracted_fields.get(field)
                    or field in absent_fields
                )
            ):
                bounded_confidences[field] = round(float(raw_confidence), 4)

        confidence_total = sum(bounded_confidences.values())
        overall_confidence = round(
            confidence_total / len(GEMINI_EXTRACTION_FIELDS),
            4,
        )
        classification_confidence = metadata.get("classification_confidence")
        if (
            isinstance(classification_confidence, (int, float))
            and not isinstance(classification_confidence, bool)
        ):
            overall_confidence = min(
                overall_confidence,
                round(max(0.0, min(1.0, float(classification_confidence))), 4),
            )

        return PassportExtractionResult(
            extracted_fields=extracted_fields,
            overall_confidence=overall_confidence,
            confidence_score={
                "overall": overall_confidence,
                "source": "gemini_image_extraction",
                "field_confidences": bounded_confidences,
                "field_coverage": round(
                    len(bounded_confidences) / len(GEMINI_EXTRACTION_FIELDS),
                    4,
                ),
                "pipeline": {
                    "name": "gemini_image_primary",
                    "local_ocr_mrz_invoked": False,
                },
            },
            mrz_raw=None,
        )

    @staticmethod
    def _local_timeout_result(timeout_seconds: float) -> PassportExtractionResult:
        return PassportExtractionResult(
            extracted_fields={
                "processing_note": "Local OCR timed out; AI image verification was attempted.",
            },
            overall_confidence=0.0,
            confidence_score={
                "overall": 0.0,
                "pipeline": {
                    "local_budget": {
                        "timeout_seconds": timeout_seconds,
                        "exhausted": True,
                    }
                },
            },
            mrz_raw=None,
        )

    @staticmethod
    def _local_failure_result(timeout_seconds: float) -> PassportExtractionResult:
        return PassportExtractionResult(
            extracted_fields={
                "processing_note": (
                    "Local OCR was unavailable; AI image verification was attempted."
                ),
            },
            overall_confidence=0.0,
            confidence_score={
                "overall": 0.0,
                "pipeline": {
                    "local_budget": {
                        "timeout_seconds": timeout_seconds,
                        "exhausted": False,
                    },
                    "local_status": "unavailable",
                },
            },
            mrz_raw=None,
        )
