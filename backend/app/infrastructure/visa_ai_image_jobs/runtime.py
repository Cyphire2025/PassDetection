"""Worker-side execution for durable Visa-photo AI generation."""

from __future__ import annotations

import hashlib
import uuid

from app.core.logging.logger import get_logger
from app.domain.exceptions.exceptions import StorageError
from app.domain.value_objects.passport_image_crop import (
    PassportImageType,
    passport_image_storage_key,
)
from app.infrastructure.ai.gemini_visa_image_edit_service import (
    GeminiVisaImageEditError,
    GeminiVisaImageEditNotConfigured,
    GeminiVisaImageEditProviderRejected,
    GeminiVisaImageEditProviderUnavailable,
    GeminiVisaImageEditRejected,
    GeminiVisaImageEditService,
)
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.passport_visa_ai_image_job_repository import (
    PassportVisaAiImageJobRepository,
)
from app.infrastructure.repositories.passport_visa_ai_image_repository import (
    PassportVisaAiImageRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository

logger = get_logger(__name__)


class VisaAiImageJobRetryRequested(RuntimeError):
    """Signal that the durable row was re-queued and Celery should redeliver."""


class _SourceImageChanged(RuntimeError):
    pass


async def run_visa_ai_image_job(*, job_id: str, submission_id: str) -> None:
    parsed_job_id = uuid.UUID(job_id)
    parsed_submission_id = uuid.UUID(submission_id)

    async with AsyncSessionFactory() as session:
        jobs = PassportVisaAiImageJobRepository(session)
        job, claimed = await jobs.claim_running(parsed_job_id)
        await session.commit()
    if not job or job.submission_id != parsed_submission_id or not claimed:
        return

    generated_storage_key = ""
    storage = MinioStorageRepository()
    try:
        async with AsyncSessionFactory() as session:
            current_job = await PassportVisaAiImageJobRepository(
                session
            ).get_for_submission(parsed_submission_id, parsed_job_id)
            submission = await PassportSubmissionRepository(session).get_by_id(
                parsed_submission_id
            )
        if current_job is None or submission is None:
            await _mark_terminal_failure(
                parsed_job_id,
                error_code="source_not_found",
                error_message="The Visa photo or submission is no longer available.",
            )
            return
        if (
            passport_image_storage_key(submission, PassportImageType.VISA_PHOTO)
            != current_job.original_source_storage_key
        ):
            await _mark_terminal_failure(
                parsed_job_id,
                error_code="source_changed",
                error_message=(
                    "The source Visa photo changed while generation was running. "
                    "Start a new generation from the current photo."
                ),
            )
            return

        source_content = await storage.get_file(current_job.input_storage_key)
        result = await GeminiVisaImageEditService().edit(
            source_content,
            prompt=current_job.prompt,
        )
        generated_storage_key = (
            f"passport-ai-library/{submission.agency_id}/{submission.id}/visa_photo/"
            f"{current_job.id.hex}.jpg"
        )
        await storage.upload_file(
            result.content,
            generated_storage_key,
            result.content_type,
        )

        async with AsyncSessionFactory() as session:
            submissions = PassportSubmissionRepository(session)
            locked = await submissions.get_by_id_for_update(parsed_submission_id)
            if (
                locked is None
                or passport_image_storage_key(locked, PassportImageType.VISA_PHOTO)
                != current_job.original_source_storage_key
            ):
                raise _SourceImageChanged

            images = PassportVisaAiImageRepository(session)
            generation = await images.get_by_storage_key(generated_storage_key)
            if generation is None:
                generation = await images.create(
                    submission_id=parsed_submission_id,
                    original_source_storage_key=current_job.original_source_storage_key,
                    input_storage_key=current_job.input_storage_key,
                    generated_storage_key=generated_storage_key,
                    prompt=current_job.prompt,
                    prompt_sha256=result.prompt_sha256,
                    content_sha256=hashlib.sha256(result.content).hexdigest(),
                    model=result.model,
                    created_by_user_id=current_job.requested_by_user_id,
                )
            await PassportVisaAiImageJobRepository(session).mark_succeeded(
                parsed_job_id,
                result_image_id=generation.id,
            )
            await AuditLogRepository(session).record(
                action="passport_visa_ai_image_generated",
                entity_type="passport_submission",
                entity_id=str(parsed_submission_id),
                agency_id=locked.agency_id,
                user_id=current_job.requested_by_user_id,
                metadata={
                    "image_type": PassportImageType.VISA_PHOTO.value,
                    "generation_id": str(generation.id),
                    "job_id": str(parsed_job_id),
                    "model": generation.model,
                    "prompt_sha256": generation.prompt_sha256,
                },
            )
            await session.commit()
        logger.info(
            "visa_ai_image_job_succeeded",
            job_id=str(parsed_job_id),
            submission_id=str(parsed_submission_id),
        )
    except _SourceImageChanged:
        await _delete_generated_best_effort(storage, generated_storage_key)
        await _mark_terminal_failure(
            parsed_job_id,
            error_code="source_changed",
            error_message=(
                "The source Visa photo changed while generation was running. "
                "Start a new generation from the current photo."
            ),
        )
    except (
        GeminiVisaImageEditNotConfigured,
        GeminiVisaImageEditRejected,
        GeminiVisaImageEditProviderRejected,
    ) as exc:
        await _delete_generated_best_effort(storage, generated_storage_key)
        await _mark_terminal_failure(
            parsed_job_id,
            error_code="generation_rejected",
            error_message=str(exc),
        )
    except (GeminiVisaImageEditProviderUnavailable, StorageError) as exc:
        await _delete_generated_best_effort(storage, generated_storage_key)
        await _mark_retryable_failure(
            parsed_job_id,
            error_code="provider_unavailable",
            error_message=str(exc),
        )
    except GeminiVisaImageEditError as exc:
        await _delete_generated_best_effort(storage, generated_storage_key)
        await _mark_terminal_failure(
            parsed_job_id,
            error_code="generation_failed",
            error_message=str(exc),
        )
    except Exception as exc:
        await _delete_generated_best_effort(storage, generated_storage_key)
        logger.error(
            "visa_ai_image_job_unexpected_failure",
            job_id=str(parsed_job_id),
            submission_id=str(parsed_submission_id),
            error_type=type(exc).__name__,
        )
        await _mark_retryable_failure(
            parsed_job_id,
            error_code="internal_failure",
            error_message=(
                "Visa AI generation was interrupted by a temporary internal error."
            ),
        )


async def _mark_retryable_failure(
    job_id: uuid.UUID,
    *,
    error_code: str,
    error_message: str,
) -> None:
    async with AsyncSessionFactory() as session:
        can_retry = await PassportVisaAiImageJobRepository(session).mark_retryable(
            job_id,
            error_code=error_code,
            error_message=error_message,
        )
        await session.commit()
    if can_retry:
        raise VisaAiImageJobRetryRequested(error_message)


async def _mark_terminal_failure(
    job_id: uuid.UUID,
    *,
    error_code: str,
    error_message: str,
) -> None:
    async with AsyncSessionFactory() as session:
        await PassportVisaAiImageJobRepository(session).mark_failed(
            job_id,
            error_code=error_code,
            error_message=error_message,
        )
        await session.commit()


async def _delete_generated_best_effort(
    storage: MinioStorageRepository,
    storage_key: str,
) -> None:
    if not storage_key:
        return
    try:
        await storage.delete_files([storage_key])
    except StorageError:
        logger.warning(
            "visa_ai_image_job_cleanup_deferred",
            object_key_hash=hashlib.sha256(storage_key.encode("utf-8")).hexdigest()[:12],
        )
