"""Passport visa ai library reads: focused workflow owner."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.domain.value_objects.passport_image_crop import (
    PassportImageType,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
)
from app.infrastructure.repositories.passport_visa_ai_image_repository import (
    PassportVisaAiImageRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.object_streaming import private_object_streaming_response
from app.presentation.api.v1.response_contracts import binary_responses
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportVisaAiImageListResponse,
)
from app.presentation.dependencies.auth import get_current_active_user

from .image_support import (
    _authorized_staff_passport_image,
)
from .response_support import _effective_crop
from .visa_ai_support import _visa_ai_library_response

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
    response_class=Response,
    responses=binary_responses("image/jpeg", range_requests=True),
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
