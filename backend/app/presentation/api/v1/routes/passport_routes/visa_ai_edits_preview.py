"""Passport visa ai edits preview: focused workflow owner."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.core.security.passport_ai_edit_token import (
    issue_passport_ai_edit_token,
)
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
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.response_contracts import binary_responses
from app.presentation.api.v1.routes.passport_image_mutation import lock_current_image_editor
from app.presentation.api.v1.routes.passport_routes.image_support import (
    _resolve_authorized_staff_passport_image,
)
from app.presentation.api.v1.schemas.passport_schemas import (
    PassportVisaAiPreviewRequest,
)
from app.presentation.dependencies.auth import get_current_active_user
from app.presentation.dependencies.csrf import require_cookie_csrf

from .image_support import (
    _visa_ai_input_storage_key,
)
from .response_support import _effective_crop
from .visa_ai_support import _visa_ai_edit_http_exception

router = APIRouter()


@router.post(
    "/{submission_id}/images/visa_photo/ai-preview",
    status_code=status.HTTP_200_OK,
    summary="Generate an identity-preserving Visa photo edit preview",
    response_class=Response,
    responses=binary_responses("image/*"),
)
async def preview_visa_ai_image_edit(
    submission_id: uuid.UUID,
    body: PassportVisaAiPreviewRequest,
    _csrf: None = Depends(require_cookie_csrf),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
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
    edit_source_key = _visa_ai_input_storage_key(
        source_key=source_key,
        effective_crop=effective,
    )
    await session.rollback()
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

    current_user, _ = await lock_current_image_editor(
        session,
        current_user=current_user,
        submission=submission,
        image_type=image_type,
        source_key=source_key,
        changed_detail="The source image changed. Refresh it and generate the edit again.",
    )
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
