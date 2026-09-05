"""Passport visa ai edits: focused workflow boundary."""

from __future__ import annotations

import asyncio
import hashlib
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.core.security.passport_ai_edit_token import (
    PassportAiEditTokenError,
    issue_passport_ai_edit_token,
    verify_passport_ai_edit_token,
)
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
from app.infrastructure.repositories.passport_image_library_repository import (
    PassportImageLibraryRepository,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportImageCropCoordinates,
    PassportImageCropResponse,
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
from .visa_ai_support import _visa_ai_edit_http_exception

router = APIRouter()


@router.post(
    "/{submission_id}/images/visa_photo/ai-preview",
    status_code=status.HTTP_200_OK,
    summary="Generate an identity-preserving Visa photo edit preview",
)
async def preview_visa_ai_image_edit(
    submission_id: uuid.UUID,
    body: PassportVisaAiPreviewRequest,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
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
    edit_source_key = _visa_ai_input_storage_key(
        source_key=source_key,
        effective_crop=effective,
    )
    normalized_prompt = " ".join(body.prompt.strip().split())
    try:
        source_content = await MinioStorageRepository().get_file(edit_source_key)
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

    revision = crop_row.revision if crop_row else 0
    token = issue_passport_ai_edit_token(
        secret=get_settings().app_secret_key,
        submission_id=submission.id,
        user_id=current_user.id,
        image_type=image_type.value,
        expected_revision=revision,
        source_storage_key=source_key,
        prompt=normalized_prompt,
        image_content=result.content,
        model=result.model,
    )
    await AuditLogRepository(session).record(
        action="passport_visa_ai_edit_previewed",
        entity_type="passport_submission",
        entity_id=str(submission.id),
        agency_id=submission.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "image_type": image_type.value,
            "crop_revision": revision,
            "prompt_sha256": result.prompt_sha256,
            "model": result.model,
        },
    )
    await session.commit()
    return Response(
        content=result.content,
        media_type=result.content_type,
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": 'inline; filename="visa-ai-preview.jpg"',
            "X-Content-Type-Options": "nosniff",
            "X-Visa-AI-Edit-Token": token,
        },
    )


@router.post(
    "/{submission_id}/images/visa_photo/ai-apply",
    response_model=PassportImageCropResponse,
    status_code=status.HTTP_200_OK,
    summary="Save a Visa AI edit with crop and sharpness metadata",
)
async def apply_visa_ai_image_edit(
    submission_id: uuid.UUID,
    image: UploadFile = File(...),
    preview_token: str = Form(..., min_length=20, max_length=2048),
    prompt: str = Form(..., min_length=3, max_length=1000),
    x: float = Form(...),
    y: float = Form(...),
    width: float = Form(...),
    height: float = Form(...),
    rotation_degrees: int = Form(..., ge=0, le=359),
    sharpness: float = Form(...),
    expected_revision: int = Form(..., ge=0),
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
    normalized_prompt = " ".join(prompt.strip().split())
    limit = get_settings().upload_max_file_size_bytes
    content = await image.read(limit + 1)
    if not content or len(content) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="The generated Visa image is empty or too large.",
        )
    try:
        preview_claims = verify_passport_ai_edit_token(
            preview_token,
            secret=get_settings().app_secret_key,
            submission_id=submission.id,
            user_id=current_user.id,
            image_type=image_type.value,
            expected_revision=expected_revision,
            source_storage_key=source_key,
            prompt=normalized_prompt,
            image_content=content,
        )
        coordinates = PassportImageCropCoordinates(
            x=x,
            y=y,
            width=width,
            height=height,
            rotation_degrees=rotation_degrees,
            sharpness=sharpness,
        )
        canonical = await asyncio.to_thread(
            render_passport_image_crop,
            content,
            x=0.0,
            y=0.0,
            width=1.0,
            height=1.0,
            rotation_degrees=0,
            sharpness=1.0,
        )
        rendered = await asyncio.to_thread(
            render_passport_image_crop,
            canonical.content,
            x=coordinates.x,
            y=coordinates.y,
            width=coordinates.width,
            height=coordinates.height,
            rotation_degrees=coordinates.rotation_degrees,
            sharpness=coordinates.sharpness,
            sharpness_algorithm_version=2,
        )
    except PassportAiEditTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except (PassportImageCropError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    edit_source_key = (
        f"passport-edits/{submission.agency_id}/{submission.id}/visa_photo/{uuid.uuid4().hex}.jpg"
    )
    derived_key = (
        f"passport-crops/{submission.agency_id}/{submission.id}/visa_photo/"
        f"{uuid.uuid4().hex}{rendered.extension}"
    )
    storage = MinioStorageRepository()
    try:
        await storage.upload_file(canonical.content, edit_source_key, canonical.content_type)
        await storage.upload_file(rendered.content, derived_key, rendered.content_type)
    except StorageError as exc:
        await _delete_crop_derivative_best_effort(
            storage,
            edit_source_key,
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
    try:
        locked = await PassportSubmissionRepository(session).get_by_id_for_update(submission.id)
        if not locked or passport_image_storage_key(locked, image_type) != source_key:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The source image changed. Refresh it and generate the edit again.",
            )
        ai_library_item = await PassportImageLibraryRepository(session).create_ai(
            submission_id=submission.id,
            image_type=image_type,
            storage_key=edit_source_key,
            original_source_storage_key=source_key,
            content_sha256=hashlib.sha256(canonical.content).hexdigest(),
            prompt=normalized_prompt,
            prompt_sha256=hashlib.sha256(normalized_prompt.encode("utf-8")).hexdigest(),
            model=preview_claims.model,
            created_by_user_id=current_user.id,
        )
        (
            crop_row,
            previous_derived_key,
            previous_edit_source_key,
        ) = await PassportImageCropRepository(session).upsert(
            submission_id=submission.id,
            image_type=image_type,
            source_storage_key=source_key,
            edit_source_storage_key=edit_source_key,
            derived_storage_key=derived_key,
            x=coordinates.x,
            y=coordinates.y,
            width=coordinates.width,
            height=coordinates.height,
            rotation_degrees=coordinates.rotation_degrees,
            sharpness=coordinates.sharpness,
            source_width=rendered.source_width,
            source_height=rendered.source_height,
            updated_by_user_id=current_user.id,
            expected_revision=expected_revision,
            sharpness_algorithm_version=2,
        )
        await AuditLogRepository(session).record(
            action="passport_visa_ai_edit_saved",
            entity_type="passport_submission",
            entity_id=str(submission.id),
            agency_id=submission.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "image_type": image_type.value,
                "crop_revision": crop_row.revision,
                "sharpness": crop_row.sharpness,
                "prompt_sha256": hashlib.sha256(normalized_prompt.encode("utf-8")).hexdigest(),
                "model": preview_claims.model,
                "library_item_id": str(ai_library_item.id),
            },
        )
        await session.commit()
    except PassportImageCropRevisionConflict as exc:
        await session.rollback()
        await _delete_crop_derivative_best_effort(
            storage, edit_source_key, submission_id=submission.id
        )
        await _delete_crop_derivative_best_effort(storage, derived_key, submission_id=submission.id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"The image edit changed (current revision {exc.current_revision}). Refresh it and try again.",
            headers={"X-Current-Crop-Revision": str(exc.current_revision)},
        ) from exc
    except Exception:
        await session.rollback()
        await _delete_crop_derivative_best_effort(
            storage, edit_source_key, submission_id=submission.id
        )
        await _delete_crop_derivative_best_effort(storage, derived_key, submission_id=submission.id)
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
        source_storage_key=source_key,
    )
