"""Whatsapp: batch status."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ROLES,
    WHATSAPP_STALE_CLAIM_AGE,
    _agency_filter,
    _broadcast_batch_summary_statement,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBatchSummaryResponse,
    WhatsAppSendResponse,
    WhatsAppSendResult,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()


@router.get(
    "/batches/{batch_id}/summary",
    response_model=WhatsAppBatchSummaryResponse,
)
async def get_broadcast_batch_summary(
    batch_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBatchSummaryResponse:
    """Return O(1)-sized progress data for a broadcast batch."""

    result = await session.execute(
        _broadcast_batch_summary_statement(
            batch_id=batch_id,
            current_user=current_user,
            stale_cutoff=datetime.now(tz=UTC) - WHATSAPP_STALE_CLAIM_AGE,
        )
    )
    summary = result.one()
    if int(summary.total) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast batch not found",
        )
    return WhatsAppBatchSummaryResponse(
        batch_id=batch_id,
        queued=int(summary.queued),
        sent=int(summary.sent),
        failed=int(summary.failed),
        delivery_unknown=int(summary.delivery_unknown),
    )


@router.get("/batches/{batch_id}", response_model=WhatsAppSendResponse)
async def get_broadcast_batch_status(
    batch_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppSendResponse:
    result = await session.execute(
        select(WhatsAppMessageLogModel, WhatsAppBroadcastRecipientModel)
        .join(
            WhatsAppBroadcastRecipientModel,
            WhatsAppBroadcastRecipientModel.id == WhatsAppMessageLogModel.recipient_id,
        )
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id == WhatsAppMessageLogModel.broadcast_group_id,
        )
        .where(
            WhatsAppMessageLogModel.batch_id == batch_id,
            *_agency_filter(current_user),
        )
        .order_by(WhatsAppMessageLogModel.created_at.asc())
    )
    rows = list(result.all())
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast batch not found",
        )

    queued_statuses = {"queued", "processing"}
    successful_statuses = {"submitted", "sent", "delivered", "read"}
    uncertain_statuses = {"delivery_unknown", "stalled"}
    stale_cutoff = datetime.now(tz=UTC) - timedelta(minutes=30)
    results: list[WhatsAppSendResult] = []
    for log, recipient in rows:
        is_stalled = log.status in queued_statuses and log.status_updated_at < stale_cutoff
        results.append(
            WhatsAppSendResult(
                recipient_id=recipient.id,
                phone_number=recipient.normalized_phone_number,
                status="stalled" if is_stalled else log.status,
                provider_message_id=log.provider_message_id,
                error_message=(
                    log.error_message
                    or (
                        "Delivery status is unknown after a worker interruption; verify before resending"
                        if is_stalled
                        else None
                    )
                ),
            )
        )
    return WhatsAppSendResponse(
        batch_id=batch_id,
        queued=sum(1 for item in results if item.status in queued_statuses),
        sent=sum(1 for item in results if item.status in successful_statuses),
        failed=sum(
            1
            for item in results
            if item.status not in queued_statuses | successful_statuses | uncertain_statuses
        ),
        delivery_unknown=sum(1 for item in results if item.status in uncertain_statuses),
        results=results,
    )
