"""Passport visa ai library generation: focused workflow owner."""

from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import StorageError
from app.domain.value_objects.passport_image_crop import (
    PassportImageType,
)
from app.infrastructure.ai.gemini_visa_image_edit_service import (
    GeminiVisaImageEditError,
    GeminiVisaImageEditService,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
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
    PassportVisaAiImageResponse,
    PassportVisaAiPreviewRequest,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

from .image_support import (
    _visa_ai_input_storage_key,
)
from .response_support import _effective_crop
from .visa_ai_support import _visa_ai_edit_http_exception, _visa_ai_library_response

router = APIRouter()


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
    submission, source_key = await _resolve_authorized_staff_passport_image(
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
    await session.rollback()
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
    await write_passport_image_objects(
        storage,
        [
            (result.content, generated_storage_key, result.content_type),
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
            changed_detail="The source image changed. Refresh it and generate the edit again.",
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
        commit_attempted = True
        await session.commit()
    except BaseException:
        await compensate_passport_image_failure(
            session,
            storage,
            [generated_storage_key],
            submission_id=submission.id,
            commit_attempted=commit_attempted,
        )
        raise

    return _visa_ai_library_response(
        submission_id=submission.id,
        generation=generation,
        current_storage_key=(effective.edit_source_storage_key if effective else None),
    )
