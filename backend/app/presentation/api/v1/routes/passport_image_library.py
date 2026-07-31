"""Shared image-library routes for Visa photos and passport pages."""

from __future__ import annotations

import asyncio
import hashlib
import io
import mimetypes
import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.passports.reextract_passport_submission_use_case import (
    ReextractPassportSubmissionUseCase,
)
from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import StorageError
from app.domain.value_objects.passport_image_crop import (
    PassportImageType,
    passport_image_storage_key,
)
from app.domain.value_objects.passport_image_library import PassportImageLibraryItem
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
from app.presentation.api.v1.routes.passports import (
    _authorized_staff_passport_image,
    _crop_response,
    _delete_crop_derivative_best_effort,
    _delete_ephemeral_edit_source_best_effort,
    _dispatch_processing_job,
    _effective_crop,
    _validated_upload_file,
)
from app.presentation.api.v1.schemas.passport_image_library_schemas import (
    PassportImageLibraryItemResponse,
    PassportImageLibraryListResponse,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportImageCropResponse,
    PassportVisaAiImageUseRequest,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


def _library_image_url(
    *,
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    item_id: uuid.UUID,
) -> str:
    return (
        f"{get_settings().api_v1_prefix}/passports/{submission_id}/images/{image_type.value}/"
        f"library/{item_id}/image"
    )


def _library_item_response(
    *,
    item: PassportImageLibraryItem,
    authoritative_source_key: str,
    current_edit_source_key: str | None,
) -> PassportImageLibraryItemResponse:
    is_current = item.storage_key == current_edit_source_key or (
        current_edit_source_key is None and item.storage_key == authoritative_source_key
    )
    return PassportImageLibraryItemResponse(
        id=item.id,
        image_type=item.image_type.value,
        image_url=_library_image_url(
            submission_id=item.submission_id,
            image_type=item.image_type,
            item_id=item.id,
        ),
        source=item.source.value,
        created_at=item.created_at,
        is_current=is_current,
        prompt=item.prompt,
        model=item.model,
    )


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


@router.post(
    "/{submission_id}/images/{image_type}/library",
    response_model=PassportImageLibraryItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a manual image and make it the current passport image",
)
async def upload_passport_image_library_item(
    submission_id: uuid.UUID,
    image_type: PassportImageType,
    background_tasks: BackgroundTasks,
    image: UploadFile = File(...),
    expected_revision: int = Form(..., ge=0),
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> PassportImageLibraryItemResponse:
    submission, source_key = await _authorized_staff_passport_image(
        submission_id=submission_id,
        image_type=image_type,
        current_user=current_user,
        session=session,
        require_editor=True,
    )
    validated = await _validated_upload_file(image, label=f"manual {image_type.value}")
    try:
        rendered = await asyncio.to_thread(
            render_passport_image_crop,
            validated.content,
            x=0.0,
            y=0.0,
            width=1.0,
            height=1.0,
            rotation_degrees=0,
            sharpness=1.0,
            sharpness_algorithm_version=2,
        )
    except PassportImageCropError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    item_key = (
        f"passport-image-library/{submission.agency_id}/{submission.id}/"
        f"{image_type.value}/manual/{uuid.uuid4().hex}.jpg"
    )
    derived_key = (
        f"passport-crops/{submission.agency_id}/{submission.id}/"
        f"{image_type.value}/{uuid.uuid4().hex}{rendered.extension}"
    )
    storage = MinioStorageRepository()
    try:
        # UploadValidator has already removed metadata and re-encoded every
        # accepted source format as a browser-safe JPEG.
        await storage.upload_file(validated.content, item_key, validated.content_type)
        await storage.upload_file(rendered.content, derived_key, rendered.content_type)
    except StorageError as exc:
        await _delete_crop_derivative_best_effort(
            storage,
            item_key,
            submission_id=submission.id,
        )
        await _delete_crop_derivative_best_effort(
            storage,
            derived_key,
            submission_id=submission.id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=exc.message,
        ) from exc

    previous_derived_key: str | None = None
    previous_edit_source_key: str | None = None
    reextract_result = None
    authoritative_source_key = source_key
    edit_source_key: str | None = item_key
    try:
        submission_repository = PassportSubmissionRepository(session)
        locked = await submission_repository.get_by_id_for_update(submission.id)
        if not locked or passport_image_storage_key(locked, image_type) != source_key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The source image changed. Refresh it and upload again.",
            )
        library_repository = PassportImageLibraryRepository(session)
        await library_repository.ensure_original(
            submission_id=submission.id,
            image_type=image_type,
            storage_key=source_key,
            created_at=getattr(submission, "created_at", None),
        )
        item = await library_repository.create_manual(
            submission_id=submission.id,
            image_type=image_type,
            storage_key=item_key,
            original_source_storage_key=source_key,
            content_sha256=hashlib.sha256(validated.content).hexdigest(),
            created_by_user_id=current_user.id,
        )
        if image_type is PassportImageType.PASSPORT_FRONT:
            authoritative_source_key = item_key
            edit_source_key = None
            locked.promote_image(item_key)
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
            x=0.0,
            y=0.0,
            width=1.0,
            height=1.0,
            rotation_degrees=0,
            sharpness=1.0,
            source_width=rendered.source_width,
            source_height=rendered.source_height,
            updated_by_user_id=current_user.id,
            expected_revision=expected_revision,
            sharpness_algorithm_version=2,
        )
        if image_type is PassportImageType.PASSPORT_FRONT:
            reextract_result = await ReextractPassportSubmissionUseCase(
                passport_repo=submission_repository,
                processing_job_repo=PassportProcessingJobRepository(session),
            ).execute(submission.id)
        await AuditLogRepository(session).record(
            action="passport_image_manually_replaced",
            entity_type="passport_submission",
            entity_id=str(submission.id),
            agency_id=submission.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "image_type": image_type.value,
                "library_item_id": str(item.id),
                "crop_revision": crop_row.revision,
                "content_sha256": item.content_sha256,
                "reextraction_queued": bool(
                    reextract_result and reextract_result.processing_job_id
                ),
            },
        )
        if reextract_result is not None:
            await _dispatch_processing_job(
                reextract_result,
                session=session,
                background_tasks=background_tasks,
            )
        else:
            await session.commit()
    except PassportImageCropRevisionConflict as exc:
        await session.rollback()
        await _delete_crop_derivative_best_effort(
            storage,
            item_key,
            submission_id=submission.id,
        )
        await _delete_crop_derivative_best_effort(
            storage,
            derived_key,
            submission_id=submission.id,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The image changed "
                f"(current revision {exc.current_revision}). Refresh it and try again."
            ),
            headers={"X-Current-Crop-Revision": str(exc.current_revision)},
        ) from exc
    except Exception:
        await session.rollback()
        await _delete_crop_derivative_best_effort(
            storage,
            item_key,
            submission_id=submission.id,
        )
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
    if previous_edit_source_key and previous_edit_source_key != item_key:
        await _delete_ephemeral_edit_source_best_effort(
            session=session,
            storage=storage,
            key=previous_edit_source_key,
            submission_id=submission.id,
        )
    return _library_item_response(
        item=item,
        authoritative_source_key=authoritative_source_key,
        current_edit_source_key=edit_source_key,
    )


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
    submission, source_key = await _authorized_staff_passport_image(
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    derived_key = (
        f"passport-crops/{submission.agency_id}/{submission.id}/"
        f"{image_type.value}/{uuid.uuid4().hex}{rendered.extension}"
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

    previous_derived_key: str | None = None
    previous_edit_source_key: str | None = None
    edit_source_key = None if item.storage_key == source_key else item.storage_key
    authoritative_source_key = source_key
    reextract_result = None
    try:
        submission_repository = PassportSubmissionRepository(session)
        locked = await submission_repository.get_by_id_for_update(submission.id)
        if not locked or passport_image_storage_key(locked, image_type) != source_key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The source image changed. Refresh it and try again.",
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
            ).execute(submission.id)
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
        if reextract_result is not None:
            await _dispatch_processing_job(
                reextract_result,
                session=session,
                background_tasks=background_tasks,
            )
        else:
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
            detail=(
                "The image changed "
                f"(current revision {exc.current_revision}). Refresh it and try again."
            ),
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
