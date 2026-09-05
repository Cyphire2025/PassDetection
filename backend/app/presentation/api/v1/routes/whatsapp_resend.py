"""Whatsapp: resend."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    active_replacement_resolution_id_for_recipient,
)
from app.infrastructure.whatsapp.publication import (
    fail_unclaimed_broadcast_rows,
    publish_whatsapp_task,
)
from app.presentation.api.v1.routes.whatsapp_scope import _configured_template_name
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ACCEPTED_STATUSES,
    WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES,
    WHATSAPP_ROLES,
    WHATSAPP_STALE_CLAIM_AGE,
    _agency_filter,
    _as_message_type,
    _composer_snapshot_from_log,
    _merge_composer_snapshot,
    _message_values,
    _resolve_send_header_image,
    _resolve_send_message_content,
    _resolve_send_passport_intro,
    _select_support_contacts,
    _support_contacts_for_group,
    _validate_passport_link,
    logger,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppResendRequest,
    WhatsAppSendRequest,
    WhatsAppSendResponse,
    WhatsAppSendResult,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.security.client_ip import trusted_client_ip

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
    state_result = await session.execute(
        select(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.recipient_id == recipient.id,
            WhatsAppRecipientMessageStateModel.message_type == message_type,
        )
        .with_for_update()
    )
    delivery_state = state_result.scalar_one_or_none()
    is_retry = bool(delivery_state and delivery_state.status == "failed")
    if not delivery_state or (
        delivery_state.status not in WHATSAPP_ACCEPTED_STATUSES and not is_retry
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Only a successfully submitted message can be resent, and only a "
                "failed message can be retried."
            ),
        )

    now = datetime.now(tz=UTC)
    stale_cutoff = now - WHATSAPP_STALE_CLAIM_AGE
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            WhatsAppMessageLogModel.status == "queued",
            WhatsAppMessageLogModel.status_updated_at < stale_cutoff,
        )
        .values(
            status="failed",
            status_updated_at=now,
            error_message="Explicit resend claim expired before provider submission",
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            WhatsAppMessageLogModel.status == "processing",
            WhatsAppMessageLogModel.status_updated_at < stale_cutoff,
        )
        .values(
            status="delivery_unknown",
            status_updated_at=now,
            error_message=(
                "Explicit resend outcome is unknown after a worker interruption; "
                "another resend is blocked"
            ),
        )
        .execution_options(synchronize_session=False)
    )
    active_resend_result = await session.execute(
        select(WhatsAppMessageLogModel).where(
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            WhatsAppMessageLogModel.status.in_(WHATSAPP_EXPLICIT_RESEND_BLOCKING_STATUSES),
        )
    )
    active_resend = active_resend_result.scalar_one_or_none()
    if active_resend:
        detail = (
            "The previous resend has an unknown delivery outcome. "
            "Verify it with the recipient before attempting another resend."
            if active_resend.status == "delivery_unknown"
            else "A resend of this message is already in progress for this recipient."
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
        )

    source_result = await session.execute(
        select(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.broadcast_group_id == group.id,
            WhatsAppMessageLogModel.recipient_id == recipient.id,
            WhatsAppMessageLogModel.message_type == message_type,
            WhatsAppMessageLogModel.status.in_(
                WHATSAPP_ACCEPTED_STATUSES | ({"failed"} if is_retry else set())
            ),
        )
        .order_by(
            WhatsAppMessageLogModel.created_at.desc(),
            WhatsAppMessageLogModel.status_updated_at.desc(),
        )
        .limit(1)
    )
    source_log = source_result.scalar_one_or_none()
    if not source_log:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The previously saved WhatsApp message could not be found",
        )
    try:
        source_snapshot = _composer_snapshot_from_log(source_log)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This older WhatsApp message cannot be safely reconstructed for resend. "
                "Send a fresh message from the normal preview instead."
            ),
        ) from exc

    settings = get_settings()
    if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp Cloud API credentials are incomplete",
        )
    configured_template_name = _configured_template_name(message_type)
    merged_body = _merge_composer_snapshot(body, source_snapshot)
    header_image_id = _resolve_send_header_image(
        message_type,
        merged_body.header_image_id,
        resend=True,
    )
    support_contacts = _select_support_contacts(
        await _support_contacts_for_group(session, group.id),
        merged_body.support_contact_ids,
        message_type=message_type,
    )
    if message_type == "passport_link" and not support_contacts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add customer support contacts before resending this message",
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
    (
        _,
        _,
        _,
        _,
        _,
        rendered_message,
        header_parameters,
        parameters,
    ) = _message_values(
        group=group,
        recipient=recipient,
        support_contacts=support_contacts,
        body=resolved_body,
    )
    template_name = configured_template_name.strip()
    if not template_name:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"WhatsApp {message_type} template name is not configured",
        )

    batch_id = uuid.uuid4()
    resend_log = WhatsAppMessageLogModel(
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
        rendered_message=rendered_message,
        header_parameter_values=header_parameters,
        template_parameter_values=parameters,
        is_explicit_resend=not is_retry,
        created_at=now,
    )
    session.add(resend_log)
    if is_retry:
        delivery_state.status = "queued"
        delivery_state.batch_id = batch_id
        delivery_state.submitted_at = None
        delivery_state.provider_status_at = None
        delivery_state.status_updated_at = now
        delivery_state.updated_at = now
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A resend of this message is already active for this recipient.",
        ) from exc

    await AuditLogRepository(session).record(
        action=(
            "whatsapp_recipient_message_retry_requested"
            if is_retry
            else "whatsapp_recipient_message_resend_requested"
        ),
        entity_type="whatsapp_broadcast_recipient",
        entity_id=str(recipient.id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=trusted_client_ip(request),
        metadata={
            "broadcast_group_id": str(group.id),
            "message_type": message_type,
            "source_message_log_id": str(source_log.id),
            "resend_batch_id": str(batch_id),
            "source_status": source_log.status,
        },
    )
    await session.commit()

    from app.infrastructure.whatsapp.tasks import process_whatsapp_broadcast

    try:
        await publish_whatsapp_task(
            process_whatsapp_broadcast,
            payload={
                "batch_id": str(batch_id),
                "message_type": message_type,
                "message_content": (
                    parameters[0] if message_type in {"welcome", "reminder"} else parameters[2]
                ),
                "passport_intro": parameters[0] if message_type == "passport_link" else None,
                "passport_link": parameters[1] if message_type == "passport_link" else None,
                "header_image_id": (header_parameters[0] if header_parameters else None),
            },
        )
    except Exception as exc:  # noqa: BLE001 - broker failure is surfaced and persisted.
        logger.error(
            "whatsapp_resend_queue_unavailable",
            extra={
                "batch_id": str(batch_id),
                "recipient_id": str(recipient.id),
                "error_type": type(exc).__name__,
            },
        )
        await fail_unclaimed_broadcast_rows(
            session,
            batch_id=batch_id,
            error_message=(
                "WHATSAPP_QUEUE_UNAVAILABLE: WhatsApp delivery queue is temporarily unavailable"
            ),
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp delivery queue is unavailable",
        ) from exc

    return WhatsAppSendResponse(
        batch_id=batch_id,
        queued=1,
        sent=0,
        failed=0,
        results=[
            WhatsAppSendResult(
                recipient_id=recipient.id,
                phone_number=recipient.normalized_phone_number,
                status="queued",
            )
        ],
    )
