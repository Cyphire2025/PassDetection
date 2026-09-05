"""Passport visa ai support: focused workflow boundary."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.value_objects.passport_visa_ai_image import PassportVisaAiImage
from app.domain.value_objects.passport_visa_ai_image_job import PassportVisaAiImageJob
from app.infrastructure.ai.gemini_visa_image_edit_service import (
    GeminiVisaImageEditError,
    GeminiVisaImageEditNotConfigured,
    GeminiVisaImageEditProviderRejected,
    GeminiVisaImageEditProviderUnavailable,
    GeminiVisaImageEditRejected,
)
from app.infrastructure.repositories.passport_visa_ai_image_job_repository import (
    PassportVisaAiImageJobRepository,
)
from app.infrastructure.repositories.passport_visa_ai_image_repository import (
    PassportVisaAiImageRepository,
)
from app.infrastructure.visa_ai_image_jobs.dispatcher import dispatch_visa_ai_image_job
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportVisaAiImageJobResponse,
    PassportVisaAiImageResponse,
)

from .response_support import _passport_visa_ai_library_image_api_url


def _visa_ai_edit_http_exception(exc: GeminiVisaImageEditError) -> HTTPException:
    if isinstance(exc, GeminiVisaImageEditRejected):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )
    if isinstance(exc, GeminiVisaImageEditNotConfigured):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    if isinstance(exc, GeminiVisaImageEditProviderUnavailable):
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        )
    if isinstance(exc, GeminiVisaImageEditProviderRejected):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        )
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=str(exc),
    )


def _visa_ai_library_response(
    *,
    submission_id: uuid.UUID,
    generation: PassportVisaAiImage,
    current_storage_key: str | None,
) -> PassportVisaAiImageResponse:
    return PassportVisaAiImageResponse(
        id=generation.id,
        image_url=_passport_visa_ai_library_image_api_url(
            submission_id,
            generation.id,
        ),
        prompt=generation.prompt,
        model=generation.model,
        created_at=generation.created_at,
        is_current=(generation.generated_storage_key == current_storage_key),
    )


async def _visa_ai_job_response(
    *,
    submission_id: uuid.UUID,
    job: PassportVisaAiImageJob,
    current_storage_key: str | None,
    session: AsyncSession,
) -> PassportVisaAiImageJobResponse:
    result = None
    if job.result_image_id:
        generation = await PassportVisaAiImageRepository(session).get_for_submission(
            submission_id,
            job.result_image_id,
        )
        if generation:
            result = _visa_ai_library_response(
                submission_id=submission_id,
                generation=generation,
                current_storage_key=current_storage_key,
            )
    return PassportVisaAiImageJobResponse(
        id=job.id,
        status=job.status,
        prompt=job.prompt,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        error_message=job.error_message,
        result=result,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


async def _dispatch_queued_visa_ai_job(
    *,
    job: PassportVisaAiImageJob,
    session: AsyncSession,
) -> PassportVisaAiImageJob:
    if job.status != "queued" or job.celery_task_id:
        return job

    # Commit the durable outbox row before publishing. If publishing fails, a
    # later short status poll retries it without rerunning work in the request.
    await session.commit()
    task_id = await dispatch_visa_ai_image_job(
        job_id=job.id,
        submission_id=job.submission_id,
    )
    repository = PassportVisaAiImageJobRepository(session)
    if task_id:
        current = await repository.get_for_submission(job.submission_id, job.id)
        if current and current.status == "queued" and not current.celery_task_id:
            await repository.set_task_id(job.id, task_id)
            await session.commit()
    refreshed = await repository.get_for_submission(job.submission_id, job.id)
    return refreshed or job


async def _recover_and_dispatch_visa_ai_job(
    *,
    job: PassportVisaAiImageJob,
    session: AsyncSession,
) -> PassportVisaAiImageJob:
    if job.status == "running":
        recovered = await PassportVisaAiImageJobRepository(session).recover_stale(job.id)
        if recovered:
            await session.commit()
            job = recovered
    return await _dispatch_queued_visa_ai_job(job=job, session=session)
