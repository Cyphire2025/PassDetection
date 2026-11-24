"""Validate and upload one authorized broadcast header image."""

from __future__ import annotations

import uuid

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.database.models import WhatsAppBroadcastGroupModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.security.upload_security import (
    UploadSecurityContext,
    UploadSecurityEvidenceError,
    UploadSecurityService,
)
from app.infrastructure.security.upload_validator import MalwareScannerUnavailableError
from app.infrastructure.whatsapp.cloud_api_provider import (
    WhatsAppCloudApiError,
    upload_whatsapp_image,
)
from app.presentation.api.v1.routes.whatsapp_archive_policy import require_active_broadcast
from app.presentation.api.v1.routes.whatsapp_shared import (
    MAX_WHATSAPP_WELCOME_IMAGE_BYTES,
    WHATSAPP_ROLES,
    WHATSAPP_UPLOAD_READ_CHUNK_BYTES,
    _agency_filter,
)
from app.presentation.api.v1.routes.whatsapp_welcome_media_authority import (
    authorized_welcome_media_upload,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppWelcomeMediaResponse
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.post(
    "/groups/{group_id}/welcome-media",
    response_model=WhatsAppWelcomeMediaResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def upload_welcome_media(
    group_id: uuid.UUID,
    image: UploadFile = File(...),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppWelcomeMediaResponse:
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel).where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )
    require_active_broadcast(group)
    group_agency_id = group.agency_id
    if image.content_type not in {"image/jpeg", "image/png"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use a JPEG or PNG image for the message header",
        )
    await session.rollback()

    payload = bytearray()
    try:
        while chunk := await image.read(WHATSAPP_UPLOAD_READ_CHUNK_BYTES):
            payload.extend(chunk)
            if len(payload) > MAX_WHATSAPP_WELCOME_IMAGE_BYTES:
                try:
                    await UploadSecurityService().validate_image(
                        content=bytes(payload),
                        filename=image.filename,
                        declared_content_type=image.content_type,
                        context=UploadSecurityContext(
                            ingestion_flow="whatsapp_welcome_image",
                            agency_id=group_agency_id,
                            user_id=current_user.id,
                        ),
                        max_bytes=MAX_WHATSAPP_WELCOME_IMAGE_BYTES,
                    )
                except ImageValidationError:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail="The message header image must be 5 MB or smaller",
                    ) from None
    finally:
        try:
            await image.close()
        except Exception:
            pass
    try:
        validated = await UploadSecurityService().validate_image(
            content=bytes(payload),
            filename=image.filename,
            declared_content_type=image.content_type,
            context=UploadSecurityContext(
                ingestion_flow="whatsapp_welcome_image",
                agency_id=group_agency_id,
                user_id=current_user.id,
            ),
            max_bytes=MAX_WHATSAPP_WELCOME_IMAGE_BYTES,
        )
    except (MalwareScannerUnavailableError, UploadSecurityEvidenceError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document security scanning is temporarily unavailable",
            headers={"Retry-After": "30"},
        ) from exc
    except ImageValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    settings = get_settings()
    try:
        async with authorized_welcome_media_upload(session, current_user, group_id):
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
                media_id = await upload_whatsapp_image(
                    client=client,
                    settings=settings,
                    file_name=validated.filename,
                    file_content=validated.content,
                    content_type=validated.content_type,
                )
    except WhatsAppCloudApiError as exc:
        response_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if exc.transient or exc.code == "WHATSAPP_PROVIDER_NOT_CONFIGURED"
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=response_status,
            detail=str(exc),
        ) from exc

    return WhatsAppWelcomeMediaResponse(
        media_id=media_id,
        file_name=validated.filename,
        content_type=validated.content_type,
    )


upload_welcome_media.__module__ = "app.presentation.api.v1.routes.whatsapp_composer"
