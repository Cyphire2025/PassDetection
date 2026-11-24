"""Passport images crop: focused workflow owner."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import StorageError
from app.domain.value_objects.passport_image_crop import (
    PassportImageType,
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
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.passport_image_mutation import lock_current_image_editor
from app.presentation.api.v1.routes.passport_image_storage_write import (
    compensate_passport_image_failure,
    write_passport_image_objects,
)
from app.presentation.api.v1.routes.passport_routes.image_support import (
    _resolve_authorized_staff_passport_image,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportImageCropResponse,
    PassportImageCropUpdateRequest,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

from .image_support import (
    _crop_response,
    _delete_crop_derivative_best_effort,
    _delete_ephemeral_edit_source_best_effort,
)
from .response_support import _effective_crop

router = APIRouter()


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
    submission, source_key = await _resolve_authorized_staff_passport_image(
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
    await session.rollback()
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
    await write_passport_image_objects(
        storage,
        [
            (rendered.content, derived_key, rendered.content_type),
        ],
        submission_id=submission.id,
    )

    previous_derived_key: str | None = None
    previous_edit_source_key: str | None = None
    commit_attempted = False
    try:
        current_user, locked = await lock_current_image_editor(
            session,
            current_user=current_user,
            submission=submission,
            image_type=image_type,
            source_key=source_key,
            changed_detail="The source image changed. Refresh it and crop again.",
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
        commit_attempted = True
        await session.commit()
    except PassportImageCropRevisionConflict as exc:
        await compensate_passport_image_failure(
            session,
            storage,
            [derived_key],
            submission_id=submission.id,
            commit_attempted=commit_attempted,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The image crop changed (current revision {exc.current_revision}). Refresh it and try again.",
            headers={"X-Current-Crop-Revision": str(exc.current_revision)},
        ) from exc
    except BaseException:
        await compensate_passport_image_failure(
            session,
            storage,
            [derived_key],
            submission_id=submission.id,
            commit_attempted=commit_attempted,
        )
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
