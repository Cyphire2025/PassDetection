"""Whatsapp: send."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, or_, select, update
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
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.whatsapp.publication import (
    fail_unclaimed_broadcast_rows,
    publish_whatsapp_task,
)
from app.presentation.api.v1.routes.whatsapp_scope import _configured_template_name
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ACCEPTED_STATUSES,
    WHATSAPP_IN_PROGRESS_STATUSES,
    WHATSAPP_ROLES,
    WHATSAPP_STALE_CLAIM_AGE,
    WHATSAPP_SUPPRESSED_STATUSES,
    WHATSAPP_UNCERTAIN_STATUSES,
    _agency_filter,
    _as_message_type,
    _group_recipients,
    _latest_composer_snapshot,
    _merge_composer_snapshot,
    _message_values,
    _resolve_send_header_image,
    _resolve_send_message_content,
    _resolve_send_passport_intro,
    _select_group_recipients,
    _select_support_contacts,
    _support_contacts_for_group,
    _validate_passport_link,
    logger,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppSendRequest,
    WhatsAppSendResponse,
    WhatsAppSendResult,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.post(
    "/groups/{group_id}/send",
    response_model=WhatsAppSendResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def send_broadcast_message(
    group_id: uuid.UUID,
    body: WhatsAppSendRequest,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppSendResponse:
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
    recipients = _select_group_recipients(all_recipients, body.recipient_ids)
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
    template_name = _configured_template_name(message_type)
    if not template_name.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"WhatsApp {message_type} template name is not configured",
        )

    passport_link = (
        _validate_passport_link(merged_body.passport_link)
        if message_type == "passport_link"
        else None
    )
    resolved_body = WhatsAppSendRequest(
        message_type=message_type,
        passport_intro=passport_intro,
        passport_link=passport_link,
        message_content=message_content,
        header_image_id=header_image_id,
        recipient_ids=merged_body.recipient_ids,
        support_contact_ids=merged_body.support_contact_ids,
    )
    batch_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    stale_cutoff = now - WHATSAPP_STALE_CLAIM_AGE

    # A queued task has not contacted Meta and is safe to reclaim. A stale
    # processing task may have submitted bytes before a worker interruption,
    # so it becomes delivery_unknown and remains suppressed.
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.broadcast_group_id == group.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.status == "queued",
            WhatsAppMessageLogModel.status_updated_at < stale_cutoff,
        )
        .values(
            status="failed",
            status_updated_at=now,
            error_message="Delivery claim expired before provider submission",
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.broadcast_group_id == group.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.status == "processing",
            WhatsAppMessageLogModel.status_updated_at < stale_cutoff,
        )
        .values(
            status="delivery_unknown",
            status_updated_at=now,
            error_message=(
                "Delivery outcome is unknown after a worker interruption; "
                "automatic resend is suppressed"
            ),
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.broadcast_group_id == group.id,
            WhatsAppRecipientMessageStateModel.message_type == message_type,
            WhatsAppRecipientMessageStateModel.status == "processing",
            WhatsAppRecipientMessageStateModel.status_updated_at < stale_cutoff,
        )
        .values(
            status="delivery_unknown",
            status_updated_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )

    claim_values = [
        {
            "id": uuid.uuid4(),
            "broadcast_group_id": group.id,
            "recipient_id": recipient.id,
            "agency_id": recipient.agency_id,
            "message_type": message_type,
            "status": "queued",
            "batch_id": batch_id,
            "submitted_at": None,
            "status_updated_at": now,
            "created_at": now,
            "updated_at": now,
        }
        for recipient in recipients
    ]
    claim_insert = pg_insert(WhatsAppRecipientMessageStateModel).values(claim_values)
    claim_statement = (
        claim_insert.on_conflict_do_update(
            constraint="uq_whatsapp_recipient_message_state",
            set_={
                "status": "queued",
                "batch_id": batch_id,
                "submitted_at": None,
                "status_updated_at": now,
                "updated_at": now,
            },
            where=or_(
                ~WhatsAppRecipientMessageStateModel.status.in_(WHATSAPP_SUPPRESSED_STATUSES),
                and_(
                    WhatsAppRecipientMessageStateModel.status == "queued",
                    WhatsAppRecipientMessageStateModel.status_updated_at < stale_cutoff,
                ),
            ),
        )
        .returning(WhatsAppRecipientMessageStateModel.recipient_id)
        .execution_options(synchronize_session=False)
    )
    claimed_result = await session.execute(claim_statement)
    claimed_recipient_ids = set(claimed_result.scalars().all())
    claimed_recipients = [
        recipient for recipient in recipients if recipient.id in claimed_recipient_ids
    ]
    unclaimed_recipient_ids = [
        recipient.id for recipient in recipients if recipient.id not in claimed_recipient_ids
    ]
    skipped_already_sent = 0
    skipped_in_progress = 0
    skipped_delivery_unknown = 0
    if unclaimed_recipient_ids:
        skipped_result = await session.execute(
            select(WhatsAppRecipientMessageStateModel.status).where(
                WhatsAppRecipientMessageStateModel.recipient_id.in_(unclaimed_recipient_ids),
                WhatsAppRecipientMessageStateModel.message_type == message_type,
            )
        )
        skipped_statuses = list(skipped_result.scalars().all())
        skipped_already_sent = sum(
            1
            for delivery_status in skipped_statuses
            if delivery_status in WHATSAPP_ACCEPTED_STATUSES
        )
        skipped_in_progress = sum(
            1
            for delivery_status in skipped_statuses
            if delivery_status in WHATSAPP_IN_PROGRESS_STATUSES
        )
        skipped_delivery_unknown = sum(
            1
            for delivery_status in skipped_statuses
            if delivery_status in WHATSAPP_UNCERTAIN_STATUSES
        )

    if not claimed_recipients:
        await session.commit()
        return WhatsAppSendResponse(
            batch_id=None,
            queued=0,
            sent=0,
            failed=0,
            skipped_already_sent=skipped_already_sent,
            skipped_in_progress=skipped_in_progress,
            skipped_delivery_unknown=skipped_delivery_unknown,
            results=[],
        )

    results: list[WhatsAppSendResult] = []
    for recipient in claimed_recipients:
        (
            _,
            _,
            _,
            _,
            _,
            rendered,
            header_parameters,
            parameters,
        ) = _message_values(
            group=group,
            recipient=recipient,
            support_contacts=support_contacts,
            body=resolved_body,
        )
        session.add(
            WhatsAppMessageLogModel(
                batch_id=batch_id,
                broadcast_group_id=group.id,
                recipient_id=recipient.id,
                agency_id=recipient.agency_id,
                message_type=message_type,
                status="queued",
                status_updated_at=now,
                provider_message_id=None,
                error_message=None,
                template_name=template_name,
                rendered_message=rendered,
                header_parameter_values=header_parameters,
                template_parameter_values=parameters,
                is_explicit_resend=False,
                created_at=now,
            )
        )
        results.append(
            WhatsAppSendResult(
                recipient_id=recipient.id,
                phone_number=recipient.normalized_phone_number,
                status="queued",
            )
        )
    await session.commit()

    from app.infrastructure.whatsapp.tasks import process_whatsapp_broadcast

    try:
        await publish_whatsapp_task(
            process_whatsapp_broadcast,
            payload={
                "batch_id": str(batch_id),
                "message_type": message_type,
                "message_content": message_content,
                "passport_intro": passport_intro,
                "passport_link": passport_link,
                "header_image_id": resolved_body.header_image_id,
            },
        )
    except Exception as exc:  # noqa: BLE001 - convert broker failures into a visible batch failure.
        logger.error(
            "whatsapp_worker_queue_unavailable",
            extra={
                "batch_id": str(batch_id),
                "error_type": type(exc).__name__,
            },
        )
        error_message = (
            "WHATSAPP_QUEUE_UNAVAILABLE: WhatsApp delivery queue is temporarily unavailable"
        )
        await fail_unclaimed_broadcast_rows(session, batch_id=batch_id, error_message=error_message)
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp delivery queue is unavailable",
        ) from exc

    return WhatsAppSendResponse(
        batch_id=batch_id,
        queued=len(results),
        sent=0,
        failed=0,
        skipped_already_sent=skipped_already_sent,
        skipped_in_progress=skipped_in_progress,
        skipped_delivery_unknown=skipped_delivery_unknown,
        results=results,
    )
