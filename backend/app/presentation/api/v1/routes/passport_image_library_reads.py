"""Passport image library reads."""

from __future__ import annotations

import io
import mimetypes
import uuid

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import StorageError
from app.domain.value_objects.passport_image_crop import (
    PassportImageType,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
)
from app.infrastructure.repositories.passport_image_library_repository import (
    PassportImageLibraryRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.response_contracts import binary_responses
from app.presentation.api.v1.routes.passport_image_library_responses import _library_item_response
from app.presentation.api.v1.routes.passports import (
    _authorized_staff_passport_image,
    _effective_crop,
)
from app.presentation.api.v1.schemas.passport_image_library_schemas import (
    PassportImageLibraryListResponse,
)
from app.presentation.dependencies.auth import get_current_active_user

router = APIRouter()


async def _ensure_original_item(
    *,
    repository: PassportImageLibraryRepository,
    submission: object,
    image_type: PassportImageType,
    source_key: str,
    session: AsyncSession,
) -> None:
    _, created = await repository.ensure_original(
        submission_id=getattr(submission, "id"),
        image_type=image_type,
        storage_key=source_key,
        created_at=getattr(submission, "created_at", None),
    )
    if created:
        await session.commit()


@router.get(
    "/{submission_id}/images/{image_type}/library",
    response_model=PassportImageLibraryListResponse,
    status_code=status.HTTP_200_OK,
    summary="List original, manual, and AI variants for one passport image",
)
async def list_passport_image_library(
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportImageLibraryListResponse:
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    repository = PassportImageLibraryRepository(session)
    await _ensure_original_item(
        repository=repository,
        submission=submission,
        image_type=image_type,
        source_key=source_key,
        session=session,
    )
    crop_row = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop_row, source_storage_key=source_key)
    current_edit_source_key = effective.edit_source_storage_key if effective else None
    items = await repository.list_for_image(submission.id, image_type)
    return PassportImageLibraryListResponse(
        items=[
            _library_item_response(
                item=item,
                authoritative_source_key=source_key,
                current_edit_source_key=current_edit_source_key,
            )
            for item in items
        ]
    )


@router.get(
    "/{submission_id}/images/{image_type}/library/{item_id}/image",
    status_code=status.HTTP_200_OK,
    summary="Stream one authorized passport image-library item",
    response_class=Response,
    responses=binary_responses("image/*"),
)
async def get_passport_image_library_item(
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    item_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    item = await PassportImageLibraryRepository(session).get_for_image(
        submission_id=submission_id,
        image_type=image_type,
        item_id=item_id,
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The image-library item was not found.",
        )
    try:
        content = await MinioStorageRepository().get_file(item.storage_key)
    except StorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc
    content_type = mimetypes.guess_type(item.storage_key)[0] or "image/jpeg"
    extension = mimetypes.guess_extension(content_type) or ".jpg"
    return StreamingResponse(
        io.BytesIO(content),
        media_type=content_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": (
                f'inline; filename="{image_type.value}-library-{item.id}{extension}"'
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )
