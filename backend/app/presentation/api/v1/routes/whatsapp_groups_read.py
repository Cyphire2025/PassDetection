"""Whatsapp: groups read."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ROLES,
    _agency_filter,
    _group_detail,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBroadcastGroupDetailResponse,
    WhatsAppBroadcastGroupResponse,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()


@router.get("/groups", response_model=list[WhatsAppBroadcastGroupResponse])
async def list_broadcast_groups(
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[WhatsAppBroadcastGroupResponse]:
    rejected_contact_count = (
        select(func.count(WhatsAppBroadcastRejectedContactModel.id))
        .where(
            WhatsAppBroadcastRejectedContactModel.broadcast_group_id
            == WhatsAppBroadcastGroupModel.id,
        )
        .correlate(WhatsAppBroadcastGroupModel)
        .scalar_subquery()
    )
    result = await session.execute(
        select(
            WhatsAppBroadcastGroupModel,
            func.count(WhatsAppBroadcastRecipientModel.id).label("recipient_count"),
            rejected_contact_count.label("rejected_contact_count"),
        )
        .outerjoin(
            WhatsAppBroadcastRecipientModel,
            and_(
                WhatsAppBroadcastRecipientModel.broadcast_group_id
                == WhatsAppBroadcastGroupModel.id,
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            ),
        )
        .where(*_agency_filter(current_user))
        .group_by(WhatsAppBroadcastGroupModel.id)
        .order_by(WhatsAppBroadcastGroupModel.created_at.desc())
    )
    return [
        WhatsAppBroadcastGroupResponse(
            id=group.id,
            name=group.name,
            organizing_company_name=group.organizing_company_name,
            recipient_count=int(recipient_count or 0),
            total_contact_count=(int(recipient_count or 0) + int(rejected_count or 0)),
            recipient_opt_in_confirmed=group.recipient_opt_in_confirmed_at is not None,
            created_at=group.created_at,
            updated_at=group.updated_at,
        )
        for group, recipient_count, rejected_count in result.all()
    ]


@router.get("/groups/{group_id}", response_model=WhatsAppBroadcastGroupDetailResponse)
async def get_broadcast_group(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
    result = await session.execute(
        select(WhatsAppBroadcastGroupModel).where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
    )
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="WhatsApp broadcast group not found"
        )
    return await _group_detail(session, group)
