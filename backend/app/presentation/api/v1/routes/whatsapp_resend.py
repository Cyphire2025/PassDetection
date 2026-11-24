"""Public single-recipient resend scope and explicit phase composition."""

from __future__ import annotations

import uuid as uuid
from datetime import UTC as UTC
from datetime import datetime as datetime

from fastapi import APIRouter as APIRouter
from fastapi import Depends as Depends
from fastapi import HTTPException as HTTPException
from fastapi import Request as Request
from fastapi import status as status
from sqlalchemy import select as select
from sqlalchemy import update as update
from sqlalchemy.exc import IntegrityError as IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession

from app.core.config.settings import get_settings as get_settings
from app.domain.entities.entities import User as User
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel as WhatsAppBroadcastGroupModel,
)
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel as WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.models import WhatsAppMessageLogModel as WhatsAppMessageLogModel
from app.infrastructure.database.models import (
    WhatsAppRecipientMessageStateModel as WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import get_db_session as get_db_session
from app.infrastructure.repositories.audit_log_repository import (
    AuditLogRepository as AuditLogRepository,
)
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    active_replacement_resolution_id_for_recipient as active_replacement_resolution_id_for_recipient,
)
from app.infrastructure.whatsapp.group_invite_policy import (
    group_invite_block_message as group_invite_block_message,
)
from app.infrastructure.whatsapp.group_invite_policy import (
    group_invite_blocking_statuses as group_invite_blocking_statuses,
)
from app.infrastructure.whatsapp.group_invite_policy import (
    message_phone_blocking_statuses as message_phone_blocking_statuses,
)
from app.infrastructure.whatsapp.group_invite_policy import (
    passport_link_block_message as passport_link_block_message,
)
from app.infrastructure.whatsapp.publication import (
    fail_unclaimed_broadcast_rows as fail_unclaimed_broadcast_rows,
)
from app.infrastructure.whatsapp.publication import publish_whatsapp_task as publish_whatsapp_task
from app.presentation.api.v1.routes.whatsapp_archive_policy import (
    require_active_broadcast as require_active_broadcast,
)
from app.presentation.api.v1.routes.whatsapp_history_resend import (
    frozen_resend_values as frozen_resend_values,
)
from app.presentation.api.v1.routes.whatsapp_history_resend import (
    historical_resend_batch as historical_resend_batch,
)
from app.presentation.api.v1.routes.whatsapp_history_resend import (
    replay_historical_resend as replay_historical_resend,
)
from app.presentation.api.v1.routes.whatsapp_history_resend import (
    saved_resend_source as saved_resend_source,
)
from app.presentation.api.v1.routes.whatsapp_history_resend import (
    saved_template_name as saved_template_name,
)
from app.presentation.api.v1.routes.whatsapp_phone_welcome import (
    claim_resend_welcome_or_reject as claim_resend_welcome_or_reject,
)
from app.presentation.api.v1.routes.whatsapp_phone_welcome import (
    enforce_broadcast_welcome_prerequisite as enforce_broadcast_welcome_prerequisite,
)
from app.presentation.api.v1.routes.whatsapp_resend_claims import read_resend_claim
from app.presentation.api.v1.routes.whatsapp_resend_payload import (
    resend_task_payload as resend_task_payload,
)
from app.presentation.api.v1.routes.whatsapp_resend_preparation import prepare_resend_attempt
from app.presentation.api.v1.routes.whatsapp_resend_publication import publish_resend_attempt
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ACCEPTED_STATUSES as WHATSAPP_ACCEPTED_STATUSES,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES as WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES,
)
from app.presentation.api.v1.routes.whatsapp_shared import WHATSAPP_ROLES as WHATSAPP_ROLES
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_STALE_CLAIM_AGE as WHATSAPP_STALE_CLAIM_AGE,
)
from app.presentation.api.v1.routes.whatsapp_shared import _agency_filter as _agency_filter
from app.presentation.api.v1.routes.whatsapp_shared import _as_message_type as _as_message_type
from app.presentation.api.v1.routes.whatsapp_shared import (
    _merge_composer_snapshot as _merge_composer_snapshot,
)
from app.presentation.api.v1.routes.whatsapp_shared import _message_values as _message_values
from app.presentation.api.v1.routes.whatsapp_shared import (
    _resolve_message_links as _resolve_message_links,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _resolve_send_header_image as _resolve_send_header_image,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _resolve_send_message_content as _resolve_send_message_content,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _resolve_send_passport_intro as _resolve_send_passport_intro,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _select_support_contacts as _select_support_contacts,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _snapshot_template_language as _snapshot_template_language,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _support_contacts_for_group as _support_contacts_for_group,
)
from app.presentation.api.v1.routes.whatsapp_shared import logger as logger
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppResendRequest as WhatsAppResendRequest,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppSendRequest as WhatsAppSendRequest,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppSendResponse as WhatsAppSendResponse,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppSendResult as WhatsAppSendResult,
)
from app.presentation.dependencies.auth import require_role as require_role
from app.presentation.dependencies.csrf import require_cookie_csrf as require_cookie_csrf
from app.presentation.security.client_ip import trusted_client_ip as trusted_client_ip

router = APIRouter()


@router.post(
    "/groups/{group_id}/recipients/{recipient_id}/resend",
    response_model=WhatsAppSendResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def resend_recipient_message(
    group_id: uuid.UUID,
    recipient_id: uuid.UUID,
    body: WhatsAppResendRequest,
    request: Request,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppSendResponse:
    group_result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
        .with_for_update()
    )
    group = group_result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )
    require_active_broadcast(group)
    if group.recipient_opt_in_confirmed_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recipient WhatsApp opt-in has not been confirmed for this list",
        )
    recipient_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.id == recipient_id,
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
        .with_for_update()
    )
    recipient = recipient_result.scalar_one_or_none()
    if not recipient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp recipient not found",
        )
    history_batch = historical_resend_batch(
        body, user_id=current_user.id, group_id=group.id, recipient_id=recipient.id
    )
    replay = await replay_historical_resend(
        session, batch_id=history_batch, group_id=group.id, recipient_id=recipient.id
    )
    if replay is not None:
        return replay
    if await active_replacement_resolution_id_for_recipient(
        session,
        recipient=recipient,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This recipient is marked as replaced in a linked passport "
                "group. Restore that replacement before sending to them."
            ),
        )
    if body.recipient_ids is not None and set(body.recipient_ids) != {recipient.id}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A resend can only target its selected recipient",
        )
    message_type = _as_message_type(body.message_type)
    claim = await read_resend_claim(session, group, recipient, message_type)
    prepared = await prepare_resend_attempt(
        session,
        group,
        recipient,
        body,
        message_type,
        history_batch,
        claim,
    )
    return await publish_resend_attempt(
        session,
        request,
        current_user,
        group,
        recipient,
        message_type,
        claim,
        prepared,
    )
