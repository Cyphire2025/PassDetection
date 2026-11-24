"""Stable QR delivery routes composed from focused policy, preview and queue owners."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.entities.entities import (
    User,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.qr.approved_passenger_qr_issuer import qr_status
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.whatsapp.phone_welcome import (
    welcome_required_reason,
    welcome_states_for_phones,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    QrDeliveryPreviewResponse,
    SendQrBroadcastRequest,
    SendQrBroadcastResponse,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

from .tour_operations_qr_delivery_policy import ACCEPTED_STATUSES as ACCEPTED_STATUSES
from .tour_operations_qr_delivery_policy import (
    AMBIGUOUS_PRIVATE_DESTINATION_REASON as AMBIGUOUS_PRIVATE_DESTINATION_REASON,
)
from .tour_operations_qr_delivery_policy import IN_PROGRESS_STATUSES as IN_PROGRESS_STATUSES
from .tour_operations_qr_delivery_policy import QR_DELIVERY_ROLES as QR_DELIVERY_ROLES
from .tour_operations_qr_delivery_policy import (
    QR_PROCESSING_STALE_AFTER as QR_PROCESSING_STALE_AFTER,
)
from .tour_operations_qr_delivery_policy import QR_QUEUED_STALE_AFTER as QR_QUEUED_STALE_AFTER
from .tour_operations_qr_delivery_policy import _agency_id as _agency_id
from .tour_operations_qr_delivery_policy import _manageable_group as _manageable_group
from .tour_operations_qr_delivery_policy import (
    _recover_stale_qr_deliveries as _recover_stale_qr_deliveries,
)
from .tour_operations_qr_delivery_preview import build_qr_delivery_preview
from .tour_operations_qr_delivery_queue import publish_qr_delivery_batch, queue_qr_deliveries
from .tour_operations_qr_delivery_roster import _linked_recipients as _linked_recipients
from .tour_operations_qr_delivery_roster import _matched_recipients as _matched_recipients
from .tour_operations_qr_delivery_roster import _passport_number as _passport_number

router = APIRouter()


async def _build_preview(
    session: AsyncSession, *, group: ClientGroupModel
) -> QrDeliveryPreviewResponse:
    """Preserve route-level call-time settings and QR-status adapters."""
    return await build_qr_delivery_preview(
        session, group=group, get_settings=get_settings, qr_status=qr_status
    )


@router.get(
    "/groups/{group_id}/qr-codes/whatsapp-preview",
    response_model=QrDeliveryPreviewResponse,
)
async def preview_qr_whatsapp_broadcast(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(QR_DELIVERY_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> QrDeliveryPreviewResponse:
    group = await _manageable_group(
        session,
        current_user=current_user,
        group_id=group_id,
    )
    recovered_count = await _recover_stale_qr_deliveries(
        session,
        group=group,
    )
    preview = await _build_preview(session, group=group)
    if recovered_count:
        await session.commit()
    return preview


@router.post(
    "/groups/{group_id}/qr-codes/whatsapp-send",
    response_model=SendQrBroadcastResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_qr_whatsapp_broadcast(
    group_id: uuid.UUID,
    payload: SendQrBroadcastRequest,
    current_user: User = Depends(require_role(QR_DELIVERY_ROLES)),
    _csrf: None = Depends(require_cookie_csrf),
    session: AsyncSession = Depends(get_db_session),
) -> SendQrBroadcastResponse:
    message_content = payload.message_content.strip()
    if not message_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The editable QR message section is required",
        )
    group = await _manageable_group(session, current_user=current_user, group_id=group_id)
    await session.execute(
        select(ClientGroupModel.id).where(ClientGroupModel.id == group.id).with_for_update()
    )
    await _recover_stale_qr_deliveries(session, group=group)
    preview = await _build_preview(session, group=group)
    requested_ids = (
        set(payload.qr_token_ids)
        if payload.qr_token_ids is not None
        else {row.qr_token_id for row in preview.recipients if row.qr_token_id and row.eligible}
    )
    selected_phones = {
        row.phone_number
        for row in preview.recipients
        if row.qr_token_id in requested_ids and row.phone_number
    }
    welcome_states = await welcome_states_for_phones(
        session, agency_id=group.agency_id, phones=selected_phones
    )
    if any((welcome_required_reason(welcome_states.get(phone)) for phone in selected_phones)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Welcome must be delivered to every selected WhatsApp number before sending QR codes. Send the remaining welcomes first, then refresh this preview.",
        )
    if not preview.can_send:
        error_status = (
            status.HTTP_503_SERVICE_UNAVAILABLE
            if not preview.template_configured
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(
            status_code=error_status,
            detail=preview.configuration_error or "QR codes are not ready to send",
        )
    eligible_rows = [
        row for row in preview.recipients if row.qr_token_id in requested_ids and row.eligible
    ]
    if not eligible_rows:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Select at least one new or safely retryable QR code",
        )
    send_batch_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    template_name = preview.template_name or ""
    queued_count = await queue_qr_deliveries(
        session,
        group=group,
        current_user=current_user,
        eligible_rows=eligible_rows,
        send_batch_id=send_batch_id,
        now=now,
        template_name=template_name,
        message_content=message_content,
    )
    await AuditLogRepository(session).record(
        action="qr_whatsapp_broadcast_queued",
        entity_type="client_group",
        entity_id=str(group.id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "send_batch_id": str(send_batch_id),
            "queued_count": queued_count,
            "message_content_length": len(message_content),
        },
    )
    await session.commit()
    await publish_qr_delivery_batch(session, send_batch_id=send_batch_id)
    attempted_count = (
        len(requested_ids) if payload.qr_token_ids is not None else len(preview.recipients)
    )
    return SendQrBroadcastResponse(
        send_batch_id=send_batch_id,
        queued_count=queued_count,
        skipped_count=max(0, attempted_count - queued_count),
        message=f"Queued {queued_count} QR code{('' if queued_count == 1 else 's')} for individual WhatsApp delivery.",
    )
