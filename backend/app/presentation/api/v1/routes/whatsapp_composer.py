"""Whatsapp: composer."""

from __future__ import annotations

import uuid
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import ImageValidationError
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppRecipientMessageStateModel,
)
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
from app.presentation.api.v1.routes.whatsapp_scope import _configured_template_name
from app.presentation.api.v1.routes.whatsapp_shared import (
    MAX_WHATSAPP_WELCOME_IMAGE_BYTES,
    WHATSAPP_ACCEPTED_STATUSES,
    WHATSAPP_ROLES,
    WHATSAPP_UPLOAD_READ_CHUNK_BYTES,
    _agency_filter,
    _as_message_type,
    _group_recipients,
    _latest_composer_snapshot,
    _merge_composer_snapshot,
    _message_values,
    _recipient_delivery_counts,
    _select_group_recipients,
    _select_support_contacts,
    _support_contacts_for_group,
    _WhatsAppComposerSnapshot,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppPreviewRequest,
    WhatsAppPreviewResponse,
    WhatsAppWelcomeMediaResponse,
)
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
        select(WhatsAppBroadcastGroupModel.agency_id).where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
    )
    group_agency_id = result.scalar_one_or_none()
    if group_agency_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )
    if image.content_type not in {"image/jpeg", "image/png"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use a JPEG or PNG image for the Welcome message",
        )

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
                        detail="The Welcome image must be 5 MB or smaller",
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


@router.post("/groups/{group_id}/preview", response_model=WhatsAppPreviewResponse)
async def preview_broadcast_message(
    group_id: uuid.UUID,
    body: WhatsAppPreviewRequest,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppPreviewResponse:
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel).where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )

    all_recipients = await _group_recipients(session, group.id)
    if not all_recipients:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This WhatsApp list has no recipients",
        )
    if body.recipient_id and body.resend_recipient_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Choose either a preview recipient or a resend recipient, not both",
        )
    recipients = _select_group_recipients(all_recipients, body.recipient_ids)
    if (
        body.resend_recipient_id
        and body.recipient_ids is not None
        and (len(recipients) != 1 or recipients[0].id != body.resend_recipient_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A resend preview can only target its selected recipient",
        )
    recipient = recipients[0]
    selected_recipient_id = body.resend_recipient_id or body.recipient_id
    if selected_recipient_id:
        selected = next(
            (item for item in recipients if item.id == selected_recipient_id),
            None,
        )
        if not selected:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Preview recipient not found in this WhatsApp list",
            )
        recipient = selected

    message_type = _as_message_type(body.message_type)
    snapshot: _WhatsAppComposerSnapshot | None = None
    content_source: Literal["default", "latest_group", "latest_recipient"] = "default"
    if body.resend_recipient_id:
        state_result = await session.execute(
            select(WhatsAppRecipientMessageStateModel).where(
                WhatsAppRecipientMessageStateModel.recipient_id == body.resend_recipient_id,
                WhatsAppRecipientMessageStateModel.message_type == message_type,
            )
        )
        target_state = state_result.scalar_one_or_none()
        if not target_state or (
            target_state.status not in WHATSAPP_ACCEPTED_STATUSES
            and target_state.status != "failed"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only a sent or failed WhatsApp message can be opened here",
            )
        snapshot = await _latest_composer_snapshot(
            session,
            group_id=group.id,
            recipient_id=body.resend_recipient_id,
            message_type=message_type,
            accepted_only=target_state.status in WHATSAPP_ACCEPTED_STATUSES,
            include_failed=target_state.status == "failed",
            include_explicit_resends=True,
        )
        if snapshot:
            content_source = "latest_recipient"
    if snapshot is None and body.resend_recipient_id is None:
        snapshot = await _latest_composer_snapshot(
            session,
            group_id=group.id,
            message_type=message_type,
            accepted_only=True,
        )
        if snapshot:
            content_source = "latest_group"
    if body.resend_recipient_id is not None and snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No saved message is available to resend or retry for this recipient",
        )
    resolved_body = _merge_composer_snapshot(body, snapshot)
    support_contacts = _select_support_contacts(
        await _support_contacts_for_group(session, group.id),
        resolved_body.support_contact_ids,
        message_type=message_type,
    )
    (
        message_type,
        passport_intro,
        passport_link,
        message_content,
        recipient_name,
        rendered,
        header_parameters,
        parameters,
    ) = _message_values(
        group=group,
        recipient=recipient,
        support_contacts=support_contacts,
        body=resolved_body,
        preview=True,
    )
    if body.resend_recipient_id is not None:
        recipient_count = 1
        eligible_count = 1
        already_sent_count = (
            1
            if target_state is not None and target_state.status in WHATSAPP_ACCEPTED_STATUSES
            else 0
        )
        in_progress_count = 0
        uncertain_count = 0
    else:
        recipient_count = len(recipients)
        (
            eligible_count,
            already_sent_count,
            in_progress_count,
            uncertain_count,
        ) = await _recipient_delivery_counts(
            session,
            recipients=recipients,
            message_type=message_type,
        )
    template_name = _configured_template_name(message_type)
    return WhatsAppPreviewResponse(
        message_type=message_type,
        template_name=template_name,
        recipient_id=recipient.id,
        recipient_name=recipient_name,
        recipient_count=recipient_count,
        eligible_recipient_count=eligible_count,
        already_sent_count=already_sent_count,
        in_progress_count=in_progress_count,
        uncertain_recipient_count=uncertain_count,
        passport_intro=passport_intro,
        passport_link=(resolved_body.passport_link or "").strip() or None,
        message_content=message_content,
        header_image_id=(resolved_body.header_image_id or "").strip() or None,
        content_source=content_source,
        rendered_message=rendered,
        header_parameter_values=header_parameters,
        parameter_values=parameters,
    )
