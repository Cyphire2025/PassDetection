"""Passport images reset: focused workflow owner."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.domain.value_objects.passport_image_crop import (
    PassportImageType,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
    PassportImageCropRevisionConflict,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.passport_image_mutation import lock_current_image_editor
from app.presentation.api.v1.routes.passport_routes.image_support import (
    _resolve_authorized_staff_passport_image,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportImageCropResetRequest,
    PassportImageCropResponse,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

from .image_support import (
    _crop_response,
    _delete_crop_derivative_best_effort,
    _delete_ephemeral_edit_source_best_effort,
)

router = APIRouter()


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
    submission, source_key = await _resolve_authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    await session.rollback()
    current_user, locked = await lock_current_image_editor(
        session,
        current_user=current_user,
        submission=submission,
        image_type=image_type,
        source_key=source_key,
        changed_detail="The source image changed. Refresh it and try again.",
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
