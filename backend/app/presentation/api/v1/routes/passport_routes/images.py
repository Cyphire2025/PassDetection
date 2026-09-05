"""Passport images: focused workflow boundary."""

from __future__ import annotations

import asyncio
import hashlib
import io
import mimetypes
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import StorageError
from app.domain.value_objects.passport_image_crop import (
    PassportImageType,
    passport_image_storage_key,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.imaging.passport_image_cropper import (
    PassportImageCropError,
    render_passport_image_crop,
    render_passport_image_thumbnail,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
    PassportImageCropRevisionConflict,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.object_streaming import private_object_streaming_response
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportImageCropResetRequest,
    PassportImageCropResponse,
    PassportImageCropUpdateRequest,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

from .image_support import (
    _authorized_staff_passport_image,
    _crop_response,
    _dashboard_thumbnail_cache,
    _delete_crop_derivative_best_effort,
    _delete_ephemeral_edit_source_best_effort,
    _load_effective_passport_image,
)
from .response_support import _effective_crop

router = APIRouter()


@router.get(
    "/{submission_id}/images/{image_type}/edit-source",
    status_code=status.HTTP_200_OK,
    summary="Stream the current full-resolution source to an authorized image editor",
)
async def get_passport_image_edit_source(
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    crop_revision: int | None = Query(default=None, ge=0),
    range_header: Annotated[str | None, Header(alias="Range")] = None,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    del crop_revision
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    crop_row = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop_row, source_storage_key=source_key)
    edit_source_key = (
        effective.edit_source_storage_key
        if effective and effective.edit_source_storage_key
        else source_key
    )
    content_type = mimetypes.guess_type(edit_source_key)[0] or "image/jpeg"
    extension = mimetypes.guess_extension(content_type) or ".jpg"
    return await private_object_streaming_response(
        storage=MinioStorageRepository(),
        key=edit_source_key,
        media_type=content_type,
        content_disposition=(f'inline; filename="{image_type.value}-edit-source{extension}"'),
        range_header=range_header,
    )


@router.get(
    "/{submission_id}/images/{image_type}",
    status_code=status.HTTP_200_OK,
    summary="Stream the effective staff view of a passport image",
)
async def get_passport_image_view(
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    crop_revision: int | None = Query(default=None, ge=0),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    del crop_revision  # cache-buster only; callers cannot select crop history
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=False,
    )
    crop_row = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop_row, source_storage_key=source_key)
    storage = MinioStorageRepository()
    content, content_type, extension = await _load_effective_passport_image(
        storage=storage,
        source_key=source_key,
        effective_crop=effective,
    )
    return StreamingResponse(
        io.BytesIO(content),
        media_type=content_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'inline; filename="{image_type.value}{extension}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/{submission_id}/images/{image_type}/thumbnail",
    status_code=status.HTTP_200_OK,
    summary="Return a bounded authenticated dashboard thumbnail",
)
async def get_passport_image_thumbnail(
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    crop_revision: int | None = Query(default=None, ge=0),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    del crop_revision  # cache-buster only; callers cannot select crop history
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=False,
    )
    crop_row = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop_row, source_storage_key=source_key)
    effective_identity = (
        effective.derived_storage_key if effective and effective.derived_storage_key else source_key
    )
    cache_key = hashlib.sha256(effective_identity.encode("utf-8")).hexdigest()
    storage = MinioStorageRepository()

    async def create_thumbnail():  # type: ignore[no-untyped-def]
        content, _, _ = await _load_effective_passport_image(
            storage=storage,
            source_key=source_key,
            effective_crop=effective,
        )
        try:
            return await asyncio.to_thread(
                render_passport_image_thumbnail,
                content,
                max_dimension=get_settings().dashboard_thumbnail_max_dimension,
            )
        except PassportImageCropError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc

    thumbnail = await _dashboard_thumbnail_cache().get_or_create(
        cache_key,
        create_thumbnail,
    )
    return Response(
        content=thumbnail.content,
        media_type=thumbnail.content_type,
        headers={
            # Passport/Visa previews are private PII. Keep them out of shared
            # and persistent browser caches; the bounded worker cache absorbs
            # repeat rendering without weakening the authorization boundary.
            "Cache-Control": "private, no-store",
            "Content-Disposition": (f'inline; filename="{image_type.value}-thumbnail.jpg"'),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/{submission_id}/images/{image_type}/original",
    status_code=status.HTTP_200_OK,
    summary="Stream an immutable original image to an authorized crop editor",
)
async def get_passport_image_original(
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    range_header: Annotated[str | None, Header(alias="Range")] = None,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> StreamingResponse:
    _, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    content_type = mimetypes.guess_type(source_key)[0] or "image/jpeg"
    extension = mimetypes.guess_extension(content_type) or ".jpg"
    return await private_object_streaming_response(
        storage=MinioStorageRepository(),
        key=source_key,
        media_type=content_type,
        content_disposition=(f'inline; filename="{image_type.value}-original{extension}"'),
        range_header=range_header,
    )


@router.get(
    "/{submission_id}/images/{image_type}/crop",
    response_model=PassportImageCropResponse,
    status_code=status.HTTP_200_OK,
    summary="Get crop-editor metadata for one passport image",
)
async def get_passport_image_crop(
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportImageCropResponse:
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    crop_row = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective = _effective_crop(crop_row, source_storage_key=source_key)
    source_width = effective.source_width if effective else None
    source_height = effective.source_height if effective else None
    return _crop_response(
        submission_id=submission.id,
        image_type=image_type,
        crop_row=crop_row,
        source_storage_key=source_key,
        source_width=source_width,
        source_height=source_height,
    )


@router.put(
    "/{submission_id}/images/{image_type}/crop",
    response_model=PassportImageCropResponse,
    status_code=status.HTTP_200_OK,
    summary="Save a non-destructive crop for one passport image",
)
async def update_passport_image_crop(
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    body: PassportImageCropUpdateRequest,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportImageCropResponse:
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    storage = MinioStorageRepository()
    existing_crop = await PassportImageCropRepository(session).get(submission.id, image_type)
    effective_existing = _effective_crop(existing_crop, source_storage_key=source_key)
    edit_source_key = (
        effective_existing.edit_source_storage_key
        if effective_existing and effective_existing.edit_source_storage_key
        else source_key
    )
    try:
        original = await storage.get_file(edit_source_key)
        rendered = await asyncio.to_thread(
            render_passport_image_crop,
            original,
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
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message
        ) from exc
    except PassportImageCropError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    derived_key = (
        f"passport-crops/{submission.agency_id}/{submission.id}/"
        f"{image_type.value}/{uuid.uuid4().hex}{rendered.extension}"
    )
    try:
        await storage.upload_file(rendered.content, derived_key, rendered.content_type)
    except StorageError as exc:
        await _delete_crop_derivative_best_effort(storage, derived_key, submission_id=submission.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=exc.message
        ) from exc

    previous_derived_key: str | None = None
    previous_edit_source_key: str | None = None
    try:
        locked = await PassportSubmissionRepository(session).get_by_id_for_update(submission.id)
        if not locked or passport_image_storage_key(locked, image_type) != source_key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The source image changed. Refresh it and crop again.",
            )
        (
            crop_row,
            previous_derived_key,
            previous_edit_source_key,
        ) = await PassportImageCropRepository(session).upsert(
            submission_id=submission.id,
            image_type=image_type,
            source_storage_key=source_key,
            edit_source_storage_key=(
                effective_existing.edit_source_storage_key if effective_existing else None
            ),
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
        )
        await AuditLogRepository(session).record(
            action="passport_image_crop_saved",
            entity_type="passport_submission",
            entity_id=str(submission.id),
            agency_id=submission.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "image_type": image_type.value,
                "crop_revision": crop_row.revision,
                "sharpness": crop_row.sharpness,
                "sharpness_algorithm_version": crop_row.sharpness_algorithm_version,
                "ai_edited": bool(crop_row.edit_source_storage_key),
            },
        )
        await session.commit()
    except PassportImageCropRevisionConflict as exc:
        await session.rollback()
        await _delete_crop_derivative_best_effort(storage, derived_key, submission_id=submission.id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The image crop changed (current revision {exc.current_revision}). Refresh it and try again.",
            headers={"X-Current-Crop-Revision": str(exc.current_revision)},
        ) from exc
    except Exception:
        await session.rollback()
        await _delete_crop_derivative_best_effort(storage, derived_key, submission_id=submission.id)
        raise

    if previous_derived_key and previous_derived_key != derived_key:
        await _delete_crop_derivative_best_effort(
            storage, previous_derived_key, submission_id=submission.id
        )
    if previous_edit_source_key and previous_edit_source_key != crop_row.edit_source_storage_key:
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


@router.delete(
    "/{submission_id}/images/{image_type}/crop",
    response_model=PassportImageCropResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset a passport image to its immutable original",
)
async def reset_passport_image_crop(
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    body: PassportImageCropResetRequest,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportImageCropResponse:
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    locked = await PassportSubmissionRepository(session).get_by_id_for_update(submission.id)
    if not locked or passport_image_storage_key(locked, image_type) != source_key:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The source image changed. Refresh it and try again.",
        )
    try:
        (
            crop_row,
            previous_derived_key,
            previous_edit_source_key,
        ) = await PassportImageCropRepository(session).reset(
            submission_id=submission.id,
            image_type=image_type,
            updated_by_user_id=current_user.id,
            expected_revision=body.expected_revision,
        )
        if crop_row is not None and previous_derived_key:
            await AuditLogRepository(session).record(
                action="passport_image_crop_reset",
                entity_type="passport_submission",
                entity_id=str(submission.id),
                agency_id=submission.agency_id,
                user_id=current_user.id,
                actor_email=current_user.email,
                metadata={"image_type": image_type.value, "crop_revision": crop_row.revision},
            )
        await session.commit()
    except PassportImageCropRevisionConflict as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The image crop changed (current revision {exc.current_revision}). Refresh it and try again.",
            headers={"X-Current-Crop-Revision": str(exc.current_revision)},
        ) from exc

    await _delete_crop_derivative_best_effort(
        MinioStorageRepository(), previous_derived_key, submission_id=submission.id
    )
    await _delete_ephemeral_edit_source_best_effort(
        session=session,
        storage=MinioStorageRepository(),
        key=previous_edit_source_key,
        submission_id=submission.id,
    )
    return _crop_response(
        submission_id=submission.id,
        image_type=image_type,
        crop_row=crop_row,
        source_storage_key=source_key,
    )
