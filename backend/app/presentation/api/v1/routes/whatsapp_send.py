"""Whatsapp: send."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal as Literal
from typing import cast as cast

from fastapi import APIRouter as APIRouter
from fastapi import Depends, HTTPException, status
from sqlalchemy import select as select
from sqlalchemy import update as update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.recipient_capacity import (
    MAX_WHATSAPP_RECIPIENTS as MAX_WHATSAPP_RECIPIENTS,
)
from app.application.use_cases.whatsapp.recipient_capacity import (
    WhatsAppRecipientCapacityExceeded as WhatsAppRecipientCapacityExceeded,
)
from app.application.use_cases.whatsapp.recipient_capacity import (
    require_whatsapp_recipient_capacity as require_whatsapp_recipient_capacity,
)
from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel as WhatsAppBroadcastGroupModel,
)
from app.infrastructure.database.models import (
    WhatsAppRecipientMessageStateModel as WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.whatsapp.group_invite_policy import (
    group_invite_blocking_statuses as group_invite_blocking_statuses,
)
from app.infrastructure.whatsapp.group_invite_policy import (
    group_invite_skip_reason as group_invite_skip_reason,
)
from app.infrastructure.whatsapp.group_invite_policy import (
    message_phone_blocking_statuses as message_phone_blocking_statuses,
)
from app.infrastructure.whatsapp.publication import (
    fail_unclaimed_broadcast_rows,
    publish_whatsapp_task,
)
from app.infrastructure.whatsapp.template_settings import configured_template_name
from app.presentation.api.v1.routes.whatsapp_archive_policy import (
    require_active_broadcast as require_active_broadcast,
)
from app.presentation.api.v1.routes.whatsapp_phone_welcome import (
    claim_broadcast_welcome_phones as claim_broadcast_welcome_phones,
)
from app.presentation.api.v1.routes.whatsapp_phone_welcome import (
    enforce_broadcast_welcome_prerequisite as enforce_broadcast_welcome_prerequisite,
)
from app.presentation.api.v1.routes.whatsapp_recipient_claims import (
    claim_broadcast_recipient_rows as claim_broadcast_recipient_rows,
)
from app.presentation.api.v1.routes.whatsapp_reminder_audience import (
    resolve_reminder_audience as resolve_reminder_audience,
)
from app.presentation.api.v1.routes.whatsapp_roster_support import (
    _active_explicit_reminder_recipient_ids as _active_explicit_reminder_recipient_ids,
)
from app.presentation.api.v1.routes.whatsapp_send_claims import claim_prepared_broadcast_send
from app.presentation.api.v1.routes.whatsapp_send_intents import (
    register_send_http_route as register_send_http_route,
)
from app.presentation.api.v1.routes.whatsapp_send_preparation import prepare_broadcast_send
from app.presentation.api.v1.routes.whatsapp_send_projection import (
    broadcast_send_worker_payload,
    build_broadcast_send_response,
)
from app.presentation.api.v1.routes.whatsapp_send_support import (
    add_frozen_broadcast_logs,
)
from app.presentation.api.v1.routes.whatsapp_send_support import (
    release_stale_broadcast_claims as release_stale_broadcast_claims,
)
from app.presentation.api.v1.routes.whatsapp_send_support import (
    send_suppression_statuses as send_suppression_statuses,
)
from app.presentation.api.v1.routes.whatsapp_send_support import (
    unclaimed_delivery_counts as unclaimed_delivery_counts,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ROLES,
    _resolve_message_links,
    _snapshot_template_language,
    logger,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_STALE_CLAIM_AGE as WHATSAPP_STALE_CLAIM_AGE,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _agency_filter as _agency_filter,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _as_message_type as _as_message_type,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _group_recipients as _group_recipients,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _latest_composer_snapshot as _latest_composer_snapshot,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _merge_composer_snapshot as _merge_composer_snapshot,
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
    _select_group_recipients as _select_group_recipients,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _select_support_contacts as _select_support_contacts,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    _support_contacts_for_group as _support_contacts_for_group,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppSendRequest,
    WhatsAppSendResponse,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()


async def send_broadcast_message(
    group_id: uuid.UUID,
    body: WhatsAppSendRequest,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppSendResponse:
    response, payload = await queue_broadcast_message(
        group_id,
        body,
        current_user=current_user,
        session=session,
    )
    await session.commit()
    if response.batch_id is None:
        return response
    from app.infrastructure.whatsapp.tasks import process_whatsapp_broadcast

    try:
        await publish_whatsapp_task(process_whatsapp_broadcast, payload=payload)
    except Exception as exc:
        logger.error(
            "whatsapp_worker_queue_unavailable",
            extra={
                "batch_id": str(response.batch_id),
                "error_type": type(exc).__name__,
            },
        )
        await fail_unclaimed_broadcast_rows(
            session,
            batch_id=response.batch_id,
            error_message="WHATSAPP_QUEUE_UNAVAILABLE: WhatsApp delivery queue is temporarily unavailable",
        )
        await session.commit()
        raise HTTPException(
            status_code=503, detail="WhatsApp delivery queue is unavailable"
        ) from exc
    return response


async def queue_broadcast_message(
    group_id: uuid.UUID,
    body: WhatsAppSendRequest,
    *,
    current_user: User,
    session: AsyncSession,
    freeze_template_language: bool = False,
    suppress_unknown_reminders: bool = False,
) -> tuple[WhatsAppSendResponse, dict[str, object]]:
    """Shared flush-only queue boundary; callers own commit and broker publication.

    A savepoint which is explicitly rolled back can project the exact website
    claims without persisting them. This function never invokes a provider.
    """
    prepared = await prepare_broadcast_send(
        group_id, body, current_user=current_user, session=session
    )
    settings = get_settings()
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp Cloud API credentials are incomplete",
        )
    template_name = await configured_template_name(session, prepared.message_type)
    if not template_name.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"WhatsApp {prepared.message_type} template name is not configured",
        )
    passport_link, group_invite_link = _resolve_message_links(prepared.merged_body)
    resolved_body = WhatsAppSendRequest(
        message_type=prepared.message_type,
        passport_intro=prepared.passport_intro,
        passport_link=passport_link,
        message_content=prepared.message_content,
        group_invite_link=group_invite_link,
        header_image_id=prepared.header_image_id,
        recipient_ids=prepared.merged_body.recipient_ids,
        support_contact_ids=prepared.merged_body.support_contact_ids,
        audience=prepared.merged_body.audience,
        audience_client_group_id=prepared.merged_body.audience_client_group_id,
        update_submission=body.update_submission,
        update_distribution=body.update_distribution,
        update_document_type=body.update_document_type,
        include_previous_recipients=body.include_previous_recipients,
    )
    batch_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    claims = await claim_prepared_broadcast_send(
        session,
        group=prepared.group,
        recipients=prepared.recipients,
        body=body,
        message_type=prepared.message_type,
        batch_id=batch_id,
        now=now,
        suppress_unknown_reminders=suppress_unknown_reminders,
        insert_factory=pg_insert,
    )
    if not claims.claimed_recipients:
        return (
            build_broadcast_send_response(prepared, claims, batch_id=None, queued=0, results=[]),
            {},
        )
    results = add_frozen_broadcast_logs(
        session,
        group=prepared.group,
        recipients=claims.claimed_recipients,
        support_contacts=prepared.support_contacts,
        body=resolved_body,
        batch_id=batch_id,
        now=now,
        template_name=template_name,
        template_language=_snapshot_template_language(settings, prepared.message_type)
        or (settings.whatsapp_template_language if freeze_template_language else None),
        log_ids=claims.welcome_log_ids,
    )
    response = build_broadcast_send_response(
        prepared, claims, batch_id=batch_id, queued=len(results), results=results
    )
    return (
        response,
        broadcast_send_worker_payload(
            batch_id=batch_id,
            message_type=prepared.message_type,
            message_content=prepared.message_content,
            passport_intro=prepared.passport_intro,
            passport_link=passport_link,
            resolved_body=resolved_body,
        ),
    )


register_send_http_route(router, queue_broadcast_message)
