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
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.whatsapp_group_list_query import (
    broadcast_group_count_projections as broadcast_group_count_projections,
)
from app.presentation.api.v1.routes.whatsapp_group_list_response import (
    broadcast_group_list_response as broadcast_group_list_response,
)
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
    archived: bool = False,
) -> list[WhatsAppBroadcastGroupResponse]:
    rejected_contact_count, import_only_source, source_contact_count = broadcast_group_count_projections()
    result = await session.execute(
        select(
            WhatsAppBroadcastGroupModel,
            func.count(WhatsAppBroadcastRecipientModel.id).label("recipient_count"),
            rejected_contact_count.label("rejected_contact_count"),
            import_only_source.label("has_import_only_source"),
            source_contact_count.label("source_contact_count"),
        )
        .outerjoin(
            WhatsAppBroadcastRecipientModel,
            and_(
                WhatsAppBroadcastRecipientModel.broadcast_group_id
                == WhatsAppBroadcastGroupModel.id,
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            ),
        )
        .where(
            *_agency_filter(current_user),
            WhatsAppBroadcastGroupModel.archived_at.is_not(None)
            if archived else WhatsAppBroadcastGroupModel.archived_at.is_(None),
        )
        .group_by(WhatsAppBroadcastGroupModel.id)
        .order_by(WhatsAppBroadcastGroupModel.created_at.desc())
    )
    return [broadcast_group_list_response(*row) for row in result.all()]



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
    return await _group_detail(session, group, current_user=current_user)
