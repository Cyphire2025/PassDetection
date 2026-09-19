"""Archive and restore broadcast lists without deleting their contacts or history."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    DocumentWhatsAppDeliveryModel,
    PassengerQrWhatsAppDeliveryModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppMessageLogModel,
    WhatsAppPhoneWelcomeAttemptModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ROLES,
    _agency_filter,
    _group_detail,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppBroadcastGroupDetailResponse
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()
ARCHIVE_BLOCKING_STATUSES = ("queued", "processing", "delivery_unknown")


async def _locked_group(
    session: AsyncSession,
    group_id: uuid.UUID,
    current_user: User,
) -> WhatsAppBroadcastGroupModel:
    group = (
        await session.execute(
            select(WhatsAppBroadcastGroupModel)
            .where(
                WhatsAppBroadcastGroupModel.id == group_id,
                *_agency_filter(current_user),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="WhatsApp broadcast group not found")
    return group


@router.post(
    "/groups/{group_id}/archive",
    response_model=WhatsAppBroadcastGroupDetailResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def archive_broadcast_group(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    group = await _locked_group(session, group_id, current_user)
    if group.archived_at is None:
        # All enqueue paths lock the broadcast before claiming deliveries. This
        # parent lock prevents a send from racing the active-delivery check.
        for model in (
            WhatsAppMessageLogModel,
            WhatsAppRecipientMessageStateModel,
            WhatsAppPhoneWelcomeAttemptModel,
            DocumentWhatsAppDeliveryModel,
            PassengerQrWhatsAppDeliveryModel,
        ):
            pending = (
                await session.execute(
                    select(model.id)
                    .where(
                        model.broadcast_group_id == group.id,
                        model.agency_id == group.agency_id,
                        model.status.in_(ARCHIVE_BLOCKING_STATUSES),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            if pending is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "WhatsApp messages are queued, sending, or awaiting delivery review. "
                        "Wait for them to finish or resolve their status before archiving this broadcast."
                    ),
                )
        group.archived_at = datetime.now(tz=UTC)
        group.updated_at = group.archived_at
        await session.flush()
    return await _group_detail(session, group, current_user=current_user)


@router.post(
    "/groups/{group_id}/restore",
    response_model=WhatsAppBroadcastGroupDetailResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def restore_broadcast_group(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    group = await _locked_group(session, group_id, current_user)
    if group.archived_at is not None:
        group.archived_at = None
        group.updated_at = datetime.now(tz=UTC)
        await session.flush()
    return await _group_detail(session, group, current_user=current_user)
