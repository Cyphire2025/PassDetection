"""Passport visa ai library: focused workflow boundary."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import StorageError
from app.domain.value_objects.passport_image_crop import (
    PassportImageType,
    passport_image_storage_key,
)
from app.infrastructure.ai.gemini_visa_image_edit_service import (
    GeminiVisaImageEditError,
    GeminiVisaImageEditService,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.imaging.passport_image_cropper import (
    PassportImageCropError,
    render_passport_image_crop,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
    PassportImageCropRevisionConflict,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.repositories.passport_visa_ai_image_repository import (
    PassportVisaAiImageRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.object_streaming import private_object_streaming_response
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportImageCropResponse,
    PassportVisaAiImageListResponse,
    PassportVisaAiImageResponse,
    PassportVisaAiImageUseRequest,
    PassportVisaAiPreviewRequest,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

from .image_support import (
    _authorized_staff_passport_image,
    _crop_response,
    _delete_crop_derivative_best_effort,
    _delete_ephemeral_edit_source_best_effort,
    _visa_ai_input_storage_key,
)
from .response_support import _effective_crop
from .visa_ai_support import _visa_ai_edit_http_exception, _visa_ai_library_response

router = APIRouter()


@router.get(
    "/{submission_id}/images/visa_photo/ai-library",
    response_model=PassportVisaAiImageListResponse,
    status_code=status.HTTP_200_OK,
    summary="List saved Visa AI image generations",
)
async def list_visa_ai_image_library(
    submission_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportVisaAiImageListResponse:
    image_type = PassportImageType.VISA_PHOTO
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    crop_row = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop_row, source_storage_key=source_key)
    current_storage_key = effective.edit_source_storage_key if effective else None
    generations = await PassportVisaAiImageRepository(session).list_for_submission(submission.id)
    return PassportVisaAiImageListResponse(
        items=[
            _visa_ai_library_response(
                submission_id=submission.id,
                generation=generation,
                current_storage_key=current_storage_key,
            )
            for generation in generations
        ]
    )


@router.get(
    "/{submission_id}/images/visa_photo/ai-library/{generation_id}/image",
    status_code=status.HTTP_200_OK,
    summary="Stream one saved Visa AI image generation",
)
async def get_visa_ai_library_image(
    submission_id: uuid.UUID,
    generation_id: uuid.UUID,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=PassportImageType.VISA_PHOTO,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    generation = await PassportVisaAiImageRepository(session).get_for_submission(
        submission_id,
        generation_id,
    )
    if not generation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The saved Visa AI image was not found.",
        )
    return await private_object_streaming_response(
        storage=MinioStorageRepository(),
        key=generation.generated_storage_key,
        media_type="image/jpeg",
        content_disposition='inline; filename="visa-ai-generation.jpg"',
        range_header=range_header,
    )


@router.post(
    "/{submission_id}/images/visa_photo/ai-library",
    response_model=PassportVisaAiImageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate and automatically save a Visa AI image",
)
async def create_visa_ai_library_image(
    submission_id: uuid.UUID,
    body: PassportVisaAiPreviewRequest,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportVisaAiImageResponse:
    image_type = PassportImageType.VISA_PHOTO
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    crop_row = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop_row, source_storage_key=source_key)
    input_storage_key = _visa_ai_input_storage_key(
        source_key=source_key,
        effective_crop=effective,
    )
    normalized_prompt = " ".join(body.prompt.strip().split())
    storage = MinioStorageRepository()
    try:
        source_content = await storage.get_file(input_storage_key)
        result = await GeminiVisaImageEditService().edit(
            source_content,
            prompt=normalized_prompt,
        )
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc
    except GeminiVisaImageEditError as exc:
        raise _visa_ai_edit_http_exception(exc) from exc

    generated_storage_key = (
        f"passport-ai-library/{submission.agency_id}/{submission.id}/visa_photo/"
        f"{uuid.uuid4().hex}.jpg"
    )
    try:
        await storage.upload_file(
            result.content,
            generated_storage_key,
            result.content_type,
        )
    except StorageError as exc:
        await _delete_crop_derivative_best_effort(
            storage,
            generated_storage_key,
            submission_id=submission.id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc

    try:
        locked = await PassportSubmissionRepository(session).get_by_id_for_update(submission.id)
        if not locked or passport_image_storage_key(locked, image_type) != source_key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The source image changed. Refresh it and generate the edit again.",
            )
        generation = await PassportVisaAiImageRepository(session).create(
            submission_id=submission.id,
            original_source_storage_key=source_key,
            input_storage_key=input_storage_key,
            generated_storage_key=generated_storage_key,
            prompt=normalized_prompt,
            prompt_sha256=result.prompt_sha256,
            content_sha256=hashlib.sha256(result.content).hexdigest(),
            model=result.model,
            created_by_user_id=current_user.id,
        )
        await AuditLogRepository(session).record(
            action="passport_visa_ai_image_generated",
            entity_type="passport_submission",
            entity_id=str(submission.id),
            agency_id=submission.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "image_type": image_type.value,
                "generation_id": str(generation.id),
                "model": generation.model,
                "prompt_sha256": generation.prompt_sha256,
            },
        )
        await session.commit()
    except Exception:
        await session.rollback()
        await _delete_crop_derivative_best_effort(
            storage,
            generated_storage_key,
            submission_id=submission.id,
        )
        raise

    return _visa_ai_library_response(
        submission_id=submission.id,
        generation=generation,
        current_storage_key=(effective.edit_source_storage_key if effective else None),
    )


@router.post(
    "/{submission_id}/images/visa_photo/ai-library/{generation_id}/use",
    response_model=PassportImageCropResponse,
    status_code=status.HTTP_200_OK,
    summary="Use one saved Visa AI image as the active Visa photo",
)
async def use_visa_ai_library_image(
    submission_id: uuid.UUID,
    generation_id: uuid.UUID,
    body: PassportVisaAiImageUseRequest,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportImageCropResponse:
    image_type = PassportImageType.VISA_PHOTO
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    generation = await PassportVisaAiImageRepository(session).get_for_submission(
        submission.id,
        generation_id,
    )
    if not generation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The saved Visa AI image was not found.",
        )
    if generation.original_source_storage_key != source_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This generated image belongs to an older source photo and cannot be used.",
        )

    storage = MinioStorageRepository()
    try:
        generated_content = await storage.get_file(generation.generated_storage_key)
        rendered = await asyncio.to_thread(
            render_passport_image_crop,
            generated_content,
            x=body.x,
            y=body.y,
            width=body.width,
            height=body.height,
            rotation_degrees=body.rotation_degrees,
            sharpness=body.sharpness,
            sharpness_algorithm_version=2,
        )
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc
    except PassportImageCropError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    derived_key = (
        f"passport-crops/{submission.agency_id}/{submission.id}/visa_photo/"
        f"{uuid.uuid4().hex}{rendered.extension}"
    )
    try:
        await storage.upload_file(rendered.content, derived_key, rendered.content_type)
    except StorageError as exc:
        await _delete_crop_derivative_best_effort(
            storage,
            derived_key,
            submission_id=submission.id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc

    try:
        locked = await PassportSubmissionRepository(session).get_by_id_for_update(submission.id)
        if not locked or passport_image_storage_key(locked, image_type) != source_key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The source image changed. Refresh it and try again.",
            )
        (
            crop_row,
            previous_derived_key,
            previous_edit_source_key,
        ) = await PassportImageCropRepository(session).upsert(
            submission_id=submission.id,
            image_type=image_type,
            source_storage_key=source_key,
            edit_source_storage_key=generation.generated_storage_key,
            derived_storage_key=derived_key,
            x=body.x,
            y=body.y,
            width=body.width,
            height=body.height,
            rotation_degrees=body.rotation_degrees,
            sharpness=body.sharpness,
            source_width=rendered.source_width,
            source_height=rendered.source_height,
            updated_by_user_id=current_user.id,
            expected_revision=body.expected_revision,
            sharpness_algorithm_version=2,
        )
        await AuditLogRepository(session).record(
            action="passport_visa_ai_image_selected",
            entity_type="passport_submission",
            entity_id=str(submission.id),
            agency_id=submission.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "generation_id": str(generation.id),
                "crop_revision": crop_row.revision,
            },
        )
        await session.commit()
    except PassportImageCropRevisionConflict as exc:
        await session.rollback()
        await _delete_crop_derivative_best_effort(
            storage,
            derived_key,
            submission_id=submission.id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The image edit changed (current revision {exc.current_revision}). Refresh it and try again.",
            headers={"X-Current-Crop-Revision": str(exc.current_revision)},
        ) from exc
    except Exception:
        await session.rollback()
        await _delete_crop_derivative_best_effort(
            storage,
            derived_key,
            submission_id=submission.id,
        )
        raise

    if previous_derived_key and previous_derived_key != derived_key:
        await _delete_crop_derivative_best_effort(
            storage,
            previous_derived_key,
            submission_id=submission.id,
        )
    if previous_edit_source_key != generation.generated_storage_key:
        await _delete_ephemeral_edit_source_best_effort(
            session=session,
            storage=storage,
            key=previous_edit_source_key,
            submission_id=submission.id,
        )
    return _crop_response(
        submission_id=submission.id,
        image_type=image_type,
        crop_row=crop_row,
        source_storage_key=source_key,
    )
