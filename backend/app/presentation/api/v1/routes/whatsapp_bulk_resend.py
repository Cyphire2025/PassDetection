"""Public scope and explicit selected-resend phase composition."""

from __future__ import annotations

import uuid as uuid
from datetime import UTC as UTC
from datetime import datetime as datetime

from fastapi import APIRouter as APIRouter
from fastapi import Depends as Depends
from fastapi import HTTPException as HTTPException
from fastapi import Request as Request
from sqlalchemy import select as select
from sqlalchemy.exc import IntegrityError as IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession as AsyncSession

from app.application.use_cases.whatsapp.message_templates import (
    GroupInviteImageRequired as GroupInviteImageRequired,
)
from app.application.use_cases.whatsapp.welcome_policy import (
    requires_prior_welcome as requires_prior_welcome,
)
from app.core.config.settings import get_settings as get_settings
from app.domain.entities.entities import User as User
from app.infrastructure.database.models import AuditLogModel as AuditLogModel
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel as WhatsAppBroadcastGroupModel,
)
from app.infrastructure.database.models import (
    WhatsAppBroadcastRecipientModel as WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.models import WhatsAppMessageLogModel as WhatsAppMessageLogModel
from app.infrastructure.database.session import get_db_session as get_db_session
from app.infrastructure.repositories.audit_log_repository import (
    AuditLogRepository as AuditLogRepository,
)
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    active_replacement_phone_numbers_for_broadcast as active_replacement_phone_numbers_for_broadcast,
)
from app.infrastructure.whatsapp.phone_welcome import (
    WELCOME_DELIVERED_STATUSES as WELCOME_DELIVERED_STATUSES,
)
from app.infrastructure.whatsapp.phone_welcome import WELCOME_REQUIRED as WELCOME_REQUIRED
from app.infrastructure.whatsapp.phone_welcome import claim_phone_welcome as claim_phone_welcome
from app.infrastructure.whatsapp.phone_welcome import (
    sync_failed_broadcast_welcomes as sync_failed_broadcast_welcomes,
)
from app.infrastructure.whatsapp.phone_welcome import (
    welcome_states_for_phones as welcome_states_for_phones,
)
from app.infrastructure.whatsapp.publication import (
    fail_unclaimed_broadcast_rows as fail_unclaimed_broadcast_rows,
)
from app.infrastructure.whatsapp.publication import publish_whatsapp_task as publish_whatsapp_task
from app.presentation.api.v1.routes.whatsapp_archive_policy import (
    require_active_broadcast as require_active_broadcast,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_claims import claim_bulk_resend_rows
from app.presentation.api.v1.routes.whatsapp_bulk_resend_composer import (
    validate_bulk_resend_edits as validate_bulk_resend_edits,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_inputs import read_bulk_resend_inputs
from app.presentation.api.v1.routes.whatsapp_bulk_resend_publication import publish_bulk_resend
from app.presentation.api.v1.routes.whatsapp_bulk_resend_selection import (
    AUDIT_ACTION as AUDIT_ACTION,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_selection import (
    replay_bulk_resend_request,
    select_bulk_resend_recipients,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_support import (
    SKIP_MESSAGES as SKIP_MESSAGES,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_support import (
    build_response as build_response,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_support import (
    expire_stale_explicit_claims as expire_stale_explicit_claims,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_support import (
    frozen_resend_log as frozen_resend_log,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_support import (
    recipient_skip_reason as recipient_skip_reason,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_support import (
    refresh_batch_response as refresh_batch_response,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_support import (
    selection_delivery_maps as selection_delivery_maps,
)
from app.presentation.api.v1.routes.whatsapp_bulk_resend_support import (
    selection_fingerprint as selection_fingerprint,
)
from app.presentation.api.v1.routes.whatsapp_shared import WHATSAPP_ROLES as WHATSAPP_ROLES
from app.presentation.api.v1.routes.whatsapp_shared import _agency_filter as _agency_filter
from app.presentation.api.v1.routes.whatsapp_shared import logger as logger
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBulkResendRequest as WhatsAppBulkResendRequest,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBulkResendResponse as WhatsAppBulkResendResponse,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppSendResult as WhatsAppSendResult,
)
from app.presentation.dependencies.auth import require_role as require_role
from app.presentation.dependencies.csrf import require_cookie_csrf as require_cookie_csrf
from app.presentation.security.client_ip import trusted_client_ip as trusted_client_ip

router = APIRouter()


@router.post(
    "/groups/{group_id}/recipients/resend",
    response_model=WhatsAppBulkResendResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def resend_selected_recipient_messages(
    group_id: uuid.UUID,
    body: WhatsAppBulkResendRequest,
    request: Request,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBulkResendResponse:
    group = (
        await session.execute(
            select(WhatsAppBroadcastGroupModel)
            .where(WhatsAppBroadcastGroupModel.id == group_id, *_agency_filter(current_user))
            .with_for_update()
        )
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="WhatsApp broadcast group not found")
    require_active_broadcast(group)
    if group.recipient_opt_in_confirmed_at is None:
        raise HTTPException(
            status_code=400, detail="Recipient WhatsApp opt-in has not been confirmed for this list"
        )
    request_scope = uuid.uuid5(group.id, f"selected-resend:{body.request_id}")
    fingerprint = selection_fingerprint(body)
    replay = await replay_bulk_resend_request(session, group, body, request_scope, fingerprint)
    if replay is not None:
        return replay
    recipients = await select_bulk_resend_recipients(session, group, body)
    inputs = await read_bulk_resend_inputs(session, group, body, recipients)
    claims = await claim_bulk_resend_rows(session, group, body, recipients, inputs)
    return await publish_bulk_resend(
        session, request, current_user, group, body, request_scope, fingerprint, claims
    )
