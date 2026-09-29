"""Whatsapp: send."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.recipient_capacity import (
    MAX_WHATSAPP_RECIPIENTS,
    WhatsAppRecipientCapacityExceeded,
    require_whatsapp_recipient_capacity,
)
from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.whatsapp.group_invite_policy import (
    group_invite_blocking_statuses,
    group_invite_skip_reason,
    message_phone_blocking_statuses,
)
from app.infrastructure.whatsapp.publication import (
    fail_unclaimed_broadcast_rows,
    publish_whatsapp_task,
)
from app.infrastructure.whatsapp.template_settings import configured_template_name
from app.presentation.api.v1.routes.whatsapp_archive_policy import require_active_broadcast
from app.presentation.api.v1.routes.whatsapp_phone_welcome import (
    claim_broadcast_welcome_phones,
    enforce_broadcast_welcome_prerequisite,
)
from app.presentation.api.v1.routes.whatsapp_recipient_claims import (
    claim_broadcast_recipient_rows as claim_broadcast_recipient_rows,
)
from app.presentation.api.v1.routes.whatsapp_reminder_audience import (
    resolve_reminder_audience,
)
from app.presentation.api.v1.routes.whatsapp_roster_support import (
    _active_explicit_reminder_recipient_ids,
)
from app.presentation.api.v1.routes.whatsapp_send_intents import register_send_http_route
from app.presentation.api.v1.routes.whatsapp_send_support import (
    add_frozen_broadcast_logs,
    broadcast_suppression_statuses,
    release_stale_broadcast_claims,
    unclaimed_delivery_counts,
)
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ROLES,
    WHATSAPP_STALE_CLAIM_AGE,
    _agency_filter,
    _as_message_type,
    _group_recipients,
    _latest_composer_snapshot,
    _merge_composer_snapshot,
    _resolve_message_links,
    _resolve_send_header_image,
    _resolve_send_message_content,
    _resolve_send_passport_intro,
    _select_group_recipients,
    _select_support_contacts,
    _snapshot_template_language,
    _support_contacts_for_group,
    logger,
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
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
        .with_for_update()
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="WhatsApp broadcast group not found"
        )
    require_active_broadcast(group)
    if group.recipient_opt_in_confirmed_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recipient WhatsApp opt-in has not been confirmed for this list",
        )

    all_recipients = await _group_recipients(session, group.id)
    if not all_recipients:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This WhatsApp list has no recipients",
        )
    try:
        require_whatsapp_recipient_capacity(
            active_count=len(all_recipients),
            activating_count=0,
        )
    except WhatsAppRecipientCapacityExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This WhatsApp list exceeds the maximum of "
                f"{MAX_WHATSAPP_RECIPIENTS} recipients. Remove extra recipients before sending."
            ),
        ) from exc
    message_type = _as_message_type(body.message_type)
    source_recipients = _select_group_recipients(all_recipients, body.recipient_ids)
    audience_resolution = await resolve_reminder_audience(
        session,
        broadcast_group=group,
        recipients=source_recipients,
        audience=body.audience,
        audience_client_group_id=body.audience_client_group_id,
        current_user=current_user,
    )
    recipients = list(audience_resolution.recipients)
    await enforce_broadcast_welcome_prerequisite(
        session,
        agency_id=group.agency_id,
        message_type=message_type,
        recipients=recipients,
    )
    support_contacts = await _support_contacts_for_group(session, group.id)
    snapshot = await _latest_composer_snapshot(
        session,
        group_id=group.id,
        message_type=message_type,
        accepted_only=True,
    )
    merged_body = _merge_composer_snapshot(body, snapshot)
    support_contacts = _select_support_contacts(
        support_contacts,
        merged_body.support_contact_ids,
        message_type=message_type,
    )
    if message_type == "passport_link" and not support_contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add customer support contacts before sending this message",
        )
    header_image_id = _resolve_send_header_image(
        message_type,
        merged_body.header_image_id,
    )
    message_content = _resolve_send_message_content(
        message_type,
        merged_body.message_content,
        group_name=group.name,
    )
    passport_intro = (
        _resolve_send_passport_intro(
            merged_body.passport_intro,
            group_name=group.name,
        )
        if message_type == "passport_link"
        else None
    )
    settings = get_settings()
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp Cloud API credentials are incomplete",
        )
    template_name = await configured_template_name(session, message_type)
    if not template_name.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"WhatsApp {message_type} template name is not configured",
        )

    passport_link, group_invite_link = _resolve_message_links(merged_body)
    resolved_body = WhatsAppSendRequest(
        message_type=message_type,
        passport_intro=passport_intro,
        passport_link=passport_link,
        message_content=message_content,
        group_invite_link=group_invite_link,
        header_image_id=header_image_id,
        recipient_ids=merged_body.recipient_ids,
        support_contact_ids=merged_body.support_contact_ids,
        audience=merged_body.audience,
        audience_client_group_id=merged_body.audience_client_group_id,
    )
    batch_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    stale_cutoff = now - WHATSAPP_STALE_CLAIM_AGE
    suppressed_statuses = broadcast_suppression_statuses(message_type, suppress_unknown_reminders)
    if suppress_unknown_reminders:
        recorded_states = await session.scalars(
            select(WhatsAppRecipientMessageStateModel.status)
            .where(
                WhatsAppRecipientMessageStateModel.recipient_id.in_(
                    [recipient.id for recipient in recipients]
                ),
                WhatsAppRecipientMessageStateModel.message_type == message_type,
            )
            .distinct()
        )
        suppressed_statuses |= frozenset(recorded_states.all()) - {
            "submitted",
            "sent",
            "delivered",
            "read",
            "failed",
        }
    await release_stale_broadcast_claims(
        session, group_id=group.id, message_type=message_type, now=now, stale_cutoff=stale_cutoff
    )

    active_explicit_reminder_ids = (
        await _active_explicit_reminder_recipient_ids(session, recipients)
        if message_type == "reminder"
        else set()
    )
    if message_type == "passport_link":
        # Its phone-history guard also reads the baseline ledger. Release the
        # same stale, unsubmitted claim that the upsert formerly reclaimed.
        await session.execute(
            update(WhatsAppRecipientMessageStateModel)
            .where(
                WhatsAppRecipientMessageStateModel.broadcast_group_id == group.id,
                WhatsAppRecipientMessageStateModel.message_type == message_type,
                WhatsAppRecipientMessageStateModel.status == "queued",
                WhatsAppRecipientMessageStateModel.status_updated_at < stale_cutoff,
            )
            .values(status="failed", batch_id=None, status_updated_at=now, updated_at=now)
            .execution_options(synchronize_session=False)
        )
    invite_blocks = (
        await group_invite_blocking_statuses(session, recipients)
        if message_type == "group_invite"
        else await message_phone_blocking_statuses(session, recipients, message_type=message_type)
        if message_type == "passport_link"
        else {}
    )
    claimed_recipient_ids = await claim_broadcast_recipient_rows(
        session,
        group_id=group.id,
        recipients=recipients,
        message_type=message_type,
        batch_id=batch_id,
        now=now,
        stale_cutoff=stale_cutoff,
        active_explicit_reminder_ids=active_explicit_reminder_ids,
        invite_blocks=invite_blocks,
        suppressed_statuses=suppressed_statuses,
        insert_factory=pg_insert,
    )
    claimed_recipients = [
        recipient for recipient in recipients if recipient.id in claimed_recipient_ids
    ]
    (
        claimed_recipients,
        welcome_log_ids,
        phone_skipped_already,
        phone_skipped_progress,
        phone_skipped_unknown,
    ) = await claim_broadcast_welcome_phones(
        session,
        agency_id=group.agency_id,
        message_type=message_type,
        recipients=claimed_recipients,
        batch_id=batch_id,
        now=now,
    )
    unclaimed_recipient_ids = [
        recipient.id
        for recipient in recipients
        if recipient.id not in claimed_recipient_ids
        and recipient.id not in active_explicit_reminder_ids
        and recipient.id not in invite_blocks
    ]
    (
        skipped_already_sent,
        skipped_in_progress,
        skipped_delivery_unknown,
    ) = await unclaimed_delivery_counts(
        session,
        recipient_ids=unclaimed_recipient_ids,
        message_type=message_type,
    )
    skipped_in_progress += len(active_explicit_reminder_ids)
    invite_reasons = [group_invite_skip_reason(value) for value in invite_blocks.values()]
    skipped_already_sent += invite_reasons.count("skipped_already_sent")
    skipped_in_progress += invite_reasons.count("skipped_in_progress")
    skipped_delivery_unknown += invite_reasons.count("skipped_delivery_unknown")
    skipped_already_sent += phone_skipped_already
    skipped_in_progress += phone_skipped_progress
    skipped_delivery_unknown += phone_skipped_unknown

    if not claimed_recipients:
        return WhatsAppSendResponse(
            batch_id=None,
            audience=cast(Literal["all", "not_submitted"], audience_resolution.audience),
            audience_client_group_id=audience_resolution.client_group_id,
            recipient_count=len(source_recipients),
            audience_recipient_count=len(recipients),
            excluded_submitted_count=(audience_resolution.excluded_submitted_count),
            excluded_needs_review_count=(audience_resolution.excluded_needs_review_count),
            queued=0,
            sent=0,
            failed=0,
            skipped_already_sent=skipped_already_sent,
            skipped_in_progress=skipped_in_progress,
            skipped_delivery_unknown=skipped_delivery_unknown,
            results=[],
        ), {}

    results = add_frozen_broadcast_logs(
        session,
        group=group,
        recipients=claimed_recipients,
        support_contacts=support_contacts,
        body=resolved_body,
        batch_id=batch_id,
        now=now,
        template_name=template_name,
        template_language=(
            _snapshot_template_language(settings, message_type)
            or (settings.whatsapp_template_language if freeze_template_language else None)
        ),
        log_ids=welcome_log_ids,
    )

    response = WhatsAppSendResponse(
        batch_id=batch_id,
        audience=cast(Literal["all", "not_submitted"], audience_resolution.audience),
        audience_client_group_id=audience_resolution.client_group_id,
        recipient_count=len(source_recipients),
        audience_recipient_count=len(recipients),
        excluded_submitted_count=audience_resolution.excluded_submitted_count,
        excluded_needs_review_count=(audience_resolution.excluded_needs_review_count),
        queued=len(results),
        sent=0,
        failed=0,
        skipped_already_sent=skipped_already_sent,
        skipped_in_progress=skipped_in_progress,
        skipped_delivery_unknown=skipped_delivery_unknown,
        results=results,
    )
    return response, {
        "batch_id": str(batch_id),
        "message_type": message_type,
        "message_content": message_content,
        "passport_intro": passport_intro,
        "passport_link": passport_link,
        "group_invite_link": resolved_body.group_invite_link,
        "header_image_id": resolved_body.header_image_id,
    }


register_send_http_route(router, queue_broadcast_message)
