"""Compatibility imports and public broadcast preview composition."""

from __future__ import annotations

import uuid as uuid
from typing import Literal as Literal
from typing import cast as cast

import httpx as httpx
from fastapi import APIRouter as APIRouter
from fastapi import Depends as Depends
from fastapi import File as File
from fastapi import HTTPException as HTTPException
from fastapi import UploadFile as UploadFile
from fastapi import status as status
from sqlalchemy import select as select
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession

from app.core.config.settings import get_settings as get_settings
from app.domain.entities.entities import User as User
from app.domain.exceptions.exceptions import ImageValidationError as ImageValidationError
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel as WhatsAppBroadcastGroupModel,
)
from app.infrastructure.database.models import (
    WhatsAppRecipientMessageStateModel as WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import get_db_session as get_db_session
from app.infrastructure.security.upload_security import (
    UploadSecurityContext as UploadSecurityContext,
)
from app.infrastructure.security.upload_security import (
    UploadSecurityEvidenceError as UploadSecurityEvidenceError,
)
from app.infrastructure.security.upload_security import (
    UploadSecurityService as UploadSecurityService,
)
from app.infrastructure.security.upload_validator import (
    MalwareScannerUnavailableError as MalwareScannerUnavailableError,
)
from app.infrastructure.whatsapp.cloud_api_provider import (
    WhatsAppCloudApiError as WhatsAppCloudApiError,
)
from app.infrastructure.whatsapp.cloud_api_provider import (
    upload_whatsapp_image as upload_whatsapp_image,
)
from app.infrastructure.whatsapp.group_invite_policy import (
    group_invite_block_message as group_invite_block_message,
)
from app.infrastructure.whatsapp.group_invite_policy import (
    group_invite_blocking_statuses as group_invite_blocking_statuses,
)
from app.infrastructure.whatsapp.template_settings import (
    configured_template_name as configured_template_name,
)
from app.presentation.api.v1.routes.whatsapp_archive_policy import (
    require_active_broadcast as require_active_broadcast,
)
from app.presentation.api.v1.routes.whatsapp_composer_media import router as _media_router
from app.presentation.api.v1.routes.whatsapp_composer_media import (
    upload_welcome_media as upload_welcome_media,
)
from app.presentation.api.v1.routes.whatsapp_composer_preview import (
    load_preview_selection,
    load_preview_snapshot,
)
from app.presentation.api.v1.routes.whatsapp_composer_preview_response import build_preview_response
from app.presentation.api.v1.routes.whatsapp_preview_recipient import (
    select_preview_recipient as select_preview_recipient,
)
from app.presentation.api.v1.routes.whatsapp_reminder_audience import (
    resolve_reminder_audience as resolve_reminder_audience,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    MAX_WHATSAPP_WELCOME_IMAGE_BYTES as MAX_WHATSAPP_WELCOME_IMAGE_BYTES,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ACCEPTED_STATUSES as WHATSAPP_ACCEPTED_STATUSES,
)
from app.presentation.api.v1.routes.whatsapp_shared import WHATSAPP_ROLES as WHATSAPP_ROLES
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_UPLOAD_READ_CHUNK_BYTES as WHATSAPP_UPLOAD_READ_CHUNK_BYTES,
)
from app.presentation.api.v1.routes.whatsapp_shared import _agency_filter as _agency_filter
from app.presentation.api.v1.routes.whatsapp_shared import _as_message_type as _as_message_type
from app.presentation.api.v1.routes.whatsapp_shared import _group_recipients as _group_recipients
from app.presentation.api.v1.routes.whatsapp_shared import (
    _latest_composer_snapshot as _latest_composer_snapshot,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _merge_composer_snapshot as _merge_composer_snapshot,
)
from app.presentation.api.v1.routes.whatsapp_shared import _message_values as _message_values
from app.presentation.api.v1.routes.whatsapp_shared import (
    _preview_message_metadata as _preview_message_metadata,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _recipient_delivery_counts as _recipient_delivery_counts,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _select_group_recipients as _select_group_recipients,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _select_support_contacts as _select_support_contacts,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _support_contacts_for_group as _support_contacts_for_group,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _WhatsAppComposerSnapshot as _WhatsAppComposerSnapshot,
)
from app.presentation.api.v1.routes.whatsapp_welcome_media_authority import (
    authorized_welcome_media_upload as authorized_welcome_media_upload,
)
from app.presentation.api.v1.routes.whatsapp_welcome_view import (
    welcome_preview_values as welcome_preview_values,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppPreviewRequest as WhatsAppPreviewRequest,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppPreviewResponse as WhatsAppPreviewResponse,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppWelcomeMediaResponse as WhatsAppWelcomeMediaResponse,
)
from app.presentation.dependencies.auth import require_role as require_role
from app.presentation.dependencies.csrf import require_cookie_csrf as require_cookie_csrf

router = APIRouter()
router.include_router(_media_router)


@router.post("/groups/{group_id}/preview", response_model=WhatsAppPreviewResponse)
async def preview_broadcast_message(
    group_id: uuid.UUID,
    body: WhatsAppPreviewRequest,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppPreviewResponse:
    selection = await load_preview_selection(session, group_id, body, current_user)
    saved = await load_preview_snapshot(
        session,
        body,
        selection.group,
        selection.recipient,
        selection.message_type,
    )
    return await build_preview_response(session, body, selection, saved)
