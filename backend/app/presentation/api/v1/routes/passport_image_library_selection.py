"""Passport image library selection."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import (
    propagate_mobile_passenger_change,
)
from app.application.use_cases.passports.reextract_passport_submission_use_case import (
    ReextractPassportSubmissionUseCase,
)
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
from app.infrastructure.processing.job_repository import PassportProcessingJobRepository
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
    PassportImageCropRevisionConflict,
)
from app.infrastructure.repositories.passport_image_library_repository import (
    PassportImageLibraryRepository,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.routes.passport_image_mutation import (
    lock_passport_image_mutation,
)
from app.presentation.api.v1.routes.passport_image_storage_write import (
    compensate_passport_image_failure,
    write_passport_image_objects,
)
from app.presentation.api.v1.routes.passport_routes.image_support import (
    _resolve_authorized_staff_passport_image,
)
from app.presentation.api.v1.routes.passports import (
    _crop_response,
    _delete_crop_derivative_best_effort,
    _delete_ephemeral_edit_source_best_effort,
    _dispatch_processing_job,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportImageCropResponse,
    PassportVisaAiImageUseRequest,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.post(
    "/{submission_id}/images/{image_type}/library/{item_id}/use",
    response_model=PassportImageCropResponse,
    status_code=status.HTTP_200_OK,
    summary="Make one original, manual, or AI library item current",
)
async def use_passport_image_library_item(
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    item_id: uuid.UUID,
    body: PassportVisaAiImageUseRequest,
    background_tasks: BackgroundTasks,
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
    item = await PassportImageLibraryRepository(session).get_for_image(
        submission_id=submission.id,
        image_type=image_type,
        item_id=item_id,
    )
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The image-library item was not found.",
        )
    await session.rollback()
    storage = MinioStorageRepository()
    try:
        content = await storage.get_file(item.storage_key)
        rendered = await asyncio.to_thread(
            render_passport_image_crop,
            content,
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
    edit_source_key = None if item.storage_key == source_key else item.storage_key
    authoritative_source_key = source_key
    reextract_result = None
    commit_attempted = False
    try:
        submission_repository = PassportSubmissionRepository(session)
        current_user, locked = await lock_passport_image_mutation(
            session,
            current_user=current_user,
            submission=submission,
            image_type=image_type,
            source_key=source_key,
        )
        if image_type is PassportImageType.PASSPORT_FRONT:
            authoritative_source_key = item.storage_key
            edit_source_key = None
            locked.promote_image(item.storage_key)
            locked.thumbnail_s3_key = None
            locked.update_reviewed_fields({})
            await submission_repository.update(locked)
        (
            crop_row,
            previous_derived_key,
            previous_edit_source_key,
        ) = await PassportImageCropRepository(session).upsert(
            submission_id=submission.id,
            image_type=image_type,
            source_storage_key=authoritative_source_key,
            edit_source_storage_key=edit_source_key,
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
        if image_type is PassportImageType.PASSPORT_FRONT:
            reextract_result = await ReextractPassportSubmissionUseCase(
                passport_repo=submission_repository,
                processing_job_repo=PassportProcessingJobRepository(session),
            ).execute(submission.id, source_image_replaced=True)
        await AuditLogRepository(session).record(
            action="passport_image_library_item_selected",
            entity_type="passport_submission",
            entity_id=str(submission.id),
            agency_id=submission.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "image_type": image_type.value,
                "library_item_id": str(item.id),
                "source": item.source.value,
                "crop_revision": crop_row.revision,
                "reextraction_queued": bool(
                    reextract_result and reextract_result.processing_job_id
                ),
            },
        )
        if image_type is PassportImageType.PASSPORT_FRONT:
            await propagate_mobile_passenger_change(
                session,
                agency_id=submission.agency_id,
                group_id=submission.group_id,
                passenger_submission_ids=[submission.id],
                actor_user_id=current_user.id,
                change_kind="documents",
                reconcile_identities=False,
            )
        commit_attempted = True
        if reextract_result is not None:
            await _dispatch_processing_job(
                reextract_result,
                session=session,
                background_tasks=background_tasks,
            )
        else:
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
            detail=(
                "The image changed "
                f"(current revision {exc.current_revision}). Refresh it and try again."
            ),
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
    if previous_edit_source_key and previous_edit_source_key != edit_source_key:
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
        source_storage_key=authoritative_source_key,
    )
