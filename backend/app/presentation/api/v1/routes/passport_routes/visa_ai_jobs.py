"""Passport visa ai jobs: focused workflow boundary."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.domain.value_objects.passport_image_crop import PassportImageType
from app.infrastructure.ai.gemini_visa_image_edit_service import (
    GeminiVisaImageEditRejected,
    GeminiVisaImageEditService,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
)
from app.infrastructure.repositories.passport_visa_ai_image_job_repository import (
    PassportVisaAiImageJobRepository,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportVisaAiImageJobResponse,
    PassportVisaAiPreviewRequest,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

from .image_support import _authorized_staff_passport_image, _visa_ai_input_storage_key
from .response_support import _effective_crop
from .visa_ai_support import (
    _dispatch_queued_visa_ai_job,
    _recover_and_dispatch_visa_ai_job,
    _visa_ai_job_response,
)

router = APIRouter()


@router.post(
    "/{submission_id}/images/visa_photo/ai-jobs",
    response_model=PassportVisaAiImageJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a durable Visa AI image generation",
)
async def create_visa_ai_image_job(
    submission_id: uuid.UUID,
    body: PassportVisaAiPreviewRequest,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportVisaAiImageJobResponse:
    image_type = PassportImageType.VISA_PHOTO
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    try:
        normalized_prompt = GeminiVisaImageEditService.validate_prompt(body.prompt)
    except GeminiVisaImageEditRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    settings = get_settings()
    google_key = settings.google_api_key.get_secret_value() if settings.google_api_key else ""
    if not settings.gemini_image_edit_model.strip() or not google_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Visa AI editing is not configured. Add "
                "GEMINI_IMAGE_EDIT_MODEL and a Google API key."
            ),
        )

    crop_row = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop_row, source_storage_key=source_key)
    input_storage_key = _visa_ai_input_storage_key(
        source_key=source_key,
        effective_crop=effective,
    )
    repository = PassportVisaAiImageJobRepository(session)
    job, created = await repository.enqueue(
        submission_id=submission.id,
        original_source_storage_key=source_key,
        input_storage_key=input_storage_key,
        prompt=normalized_prompt,
        requested_by_user_id=current_user.id,
    )
    if created:
        await AuditLogRepository(session).record(
            action="passport_visa_ai_image_queued",
            entity_type="passport_submission",
            entity_id=str(submission.id),
            agency_id=submission.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "image_type": image_type.value,
                "job_id": str(job.id),
                "prompt_sha256": job.prompt_sha256,
            },
        )
    job = await _dispatch_queued_visa_ai_job(job=job, session=session)
    return await _visa_ai_job_response(
        submission_id=submission.id,
        job=job,
        current_storage_key=(effective.edit_source_storage_key if effective else None),
        session=session,
    )


@router.get(
    "/{submission_id}/images/visa_photo/ai-jobs/active",
    response_model=PassportVisaAiImageJobResponse | None,
    status_code=status.HTTP_200_OK,
    summary="Resume the active Visa AI image generation, if any",
)
async def get_active_visa_ai_image_job(
    submission_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportVisaAiImageJobResponse | None:
    image_type = PassportImageType.VISA_PHOTO
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    job = await PassportVisaAiImageJobRepository(session).active_for_submission(submission.id)
    if job is None:
        return None
    job = await _recover_and_dispatch_visa_ai_job(job=job, session=session)
    crop_row = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop_row, source_storage_key=source_key)
    return await _visa_ai_job_response(
        submission_id=submission.id,
        job=job,
        current_storage_key=(effective.edit_source_storage_key if effective else None),
        session=session,
    )


@router.get(
    "/{submission_id}/images/visa_photo/ai-jobs/{job_id}",
    response_model=PassportVisaAiImageJobResponse,
    status_code=status.HTTP_200_OK,
    summary="Get one durable Visa AI image generation job",
)
async def get_visa_ai_image_job(
    submission_id: uuid.UUID,
    job_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportVisaAiImageJobResponse:
    image_type = PassportImageType.VISA_PHOTO
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    job = await PassportVisaAiImageJobRepository(session).get_for_submission(
        submission.id,
        job_id,
    )
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The Visa AI generation job was not found.",
        )
    job = await _recover_and_dispatch_visa_ai_job(job=job, session=session)
    crop_row = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop_row, source_storage_key=source_key)
    return await _visa_ai_job_response(
        submission_id=submission.id,
        job=job,
        current_storage_key=(effective.edit_source_storage_key if effective else None),
        session=session,
    )
