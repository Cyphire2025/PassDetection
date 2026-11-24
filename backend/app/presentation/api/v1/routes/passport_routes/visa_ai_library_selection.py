"""Passport visa ai library selection: focused workflow owner."""

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
from app.infrastructure.repositories.passport_visa_ai_image_repository import (
    PassportVisaAiImageRepository,
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
    PassportVisaAiImageUseRequest,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

from .image_support import (
    _crop_response,
    _delete_crop_derivative_best_effort,
    _delete_ephemeral_edit_source_best_effort,
)

router = APIRouter()


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
    submission, source_key = await _resolve_authorized_staff_passport_image(
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

    await session.rollback()
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
    await write_passport_image_objects(
        storage,
        [
            (rendered.content, derived_key, rendered.content_type),
        ],
        submission_id=submission.id,
    )

    commit_attempted = False
    try:
        current_user, locked = await lock_current_image_editor(
            session,
            current_user=current_user,
            submission=submission,
            image_type=image_type,
            source_key=source_key,
            changed_detail="The source image changed. Refresh it and try again.",
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
            detail=f"The image edit changed (current revision {exc.current_revision}). Refresh it and try again.",
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
