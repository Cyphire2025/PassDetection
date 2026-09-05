"""Whatsapp: rejected contacts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import (
    reconcile_mobile_passenger_access_for_broadcast,
)
from app.application.use_cases.whatsapp.recipient_capacity import (
    MAX_WHATSAPP_RECIPIENTS,
    WhatsAppRecipientCapacityExceeded,
)
from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    suppress_active_replacement_recipients,
)
from app.infrastructure.repositories.whatsapp_recipient_capacity_repository import (
    require_locked_broadcast_recipient_capacity,
)
from app.presentation.api.v1.routes.whatsapp_scope import _prepare_private_recipient_mutation
from app.presentation.api.v1.routes.whatsapp_shared import (
    WHATSAPP_ROLES,
    _agency_filter,
    _clean_name,
    _group_detail,
    _next_roster_display_order,
    _normalize_phone,
    _rejected_contact_response,
    _safe_imported_fields,
)
from app.presentation.api.v1.schemas.whatsapp_schemas import (
    WhatsAppBroadcastGroupDetailResponse,
    WhatsAppRejectedContactListResponse,
    WhatsAppRejectedContactResolveRequest,
)
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.get(
    "/groups/{group_id}/rejected-contacts",
    response_model=WhatsAppRejectedContactListResponse,
)
async def list_broadcast_rejected_contacts(
    group_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppRejectedContactListResponse:
    group_result = await session.execute(
        select(WhatsAppBroadcastGroupModel.id).where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
    )
    if group_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp broadcast group not found",
        )

    total_result = await session.execute(
        select(func.count())
        .select_from(WhatsAppBroadcastRejectedContactModel)
        .where(
            WhatsAppBroadcastRejectedContactModel.broadcast_group_id == group_id,
        )
    )
    total = int(total_result.scalar_one())
    items_result = await session.execute(
        select(WhatsAppBroadcastRejectedContactModel)
        .where(
            WhatsAppBroadcastRejectedContactModel.broadcast_group_id == group_id,
        )
        .order_by(
            WhatsAppBroadcastRejectedContactModel.created_at.desc(),
            WhatsAppBroadcastRejectedContactModel.source_file_name.asc(),
            WhatsAppBroadcastRejectedContactModel.sheet_name.asc(),
            WhatsAppBroadcastRejectedContactModel.row_number.asc(),
            WhatsAppBroadcastRejectedContactModel.id.asc(),
        )
        .limit(limit)
        .offset(offset)
    )
    return WhatsAppRejectedContactListResponse(
        items=[_rejected_contact_response(model) for model in items_result.scalars().all()],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/groups/{group_id}/rejected-contacts/{rejected_contact_id}/resolve",
    response_model=WhatsAppBroadcastGroupDetailResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def resolve_broadcast_rejected_contact(
    group_id: uuid.UUID,
    rejected_contact_id: uuid.UUID,
    body: WhatsAppRejectedContactResolveRequest,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> WhatsAppBroadcastGroupDetailResponse:
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

    rejected_result = await session.execute(
        select(WhatsAppBroadcastRejectedContactModel)
        .where(
            WhatsAppBroadcastRejectedContactModel.id == rejected_contact_id,
            WhatsAppBroadcastRejectedContactModel.broadcast_group_id == group.id,
        )
        .with_for_update()
    )
    rejected_contact = rejected_result.scalar_one_or_none()
    if not rejected_contact:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Rejected WhatsApp contact not found",
        )

    name = _clean_name(body.name)
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Recipient name is required",
        )
    normalized_phone = _normalize_phone(body.phone_number)
    if not normalized_phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Use a 10-digit Indian mobile number, or an international number "
                "of 8 to 15 digits with its country code"
            ),
        )
    if not body.recipient_opt_in_confirmed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirm this recipient agreed to receive WhatsApp updates",
        )

    existing_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
            WhatsAppBroadcastRecipientModel.normalized_phone_number == normalized_phone,
        )
        .with_for_update()
    )
    existing_recipient = existing_result.scalar_one_or_none()
    if existing_recipient and existing_recipient.removed_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That WhatsApp number is already in the valid recipient list",
        )
    if existing_recipient and existing_recipient.suppressed_by_roster_resolution_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This recipient is currently marked as replaced in a "
                "linked passport group. Restore that replacement from "
                "the group before adding them back."
            ),
        )
    try:
        await require_locked_broadcast_recipient_capacity(
            session,
            agency_id=group.agency_id,
            locked_broadcast_ids=[group.id],
            activating_by_broadcast={group.id: 1},
        )
    except WhatsAppRecipientCapacityExceeded as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This WhatsApp list already contains the maximum of "
                f"{MAX_WHATSAPP_RECIPIENTS} valid recipients"
            ),
        ) from exc

    await _prepare_private_recipient_mutation(
        session,
        agency_id=group.agency_id,
        broadcast_group_id=group.id,
        cancellation_reason=("WhatsApp recipients changed before private document or QR delivery"),
    )
    now = datetime.now(tz=UTC)
    imported_fields = dict(rejected_contact.imported_fields or {})
    imported_fields.setdefault("source_file", rejected_contact.source_file_name)
    imported_fields.setdefault("source_sheet", rejected_contact.sheet_name)
    imported_fields.setdefault("source_row", str(rejected_contact.row_number))
    imported_fields = _safe_imported_fields(imported_fields)
    resolved_display_order = rejected_contact.display_order
    if resolved_display_order is None:
        resolved_display_order = await _next_roster_display_order(session, group.id)
    if existing_recipient:
        existing_recipient.name = name
        existing_recipient.phone_number = body.phone_number.strip()
        existing_recipient.imported_fields = imported_fields
        if existing_recipient.display_order is None:
            existing_recipient.display_order = resolved_display_order
        existing_recipient.removed_at = None
        await session.execute(
            delete(WhatsAppRecipientMessageStateModel).where(
                WhatsAppRecipientMessageStateModel.recipient_id == existing_recipient.id,
            )
        )
    else:
        session.add(
            WhatsAppBroadcastRecipientModel(
                broadcast_group_id=group.id,
                agency_id=group.agency_id,
                name=name,
                phone_number=body.phone_number.strip(),
                normalized_phone_number=normalized_phone,
                imported_fields=imported_fields,
                display_order=resolved_display_order,
                created_at=now,
            )
        )

    await session.execute(
        delete(WhatsAppBroadcastRejectedContactModel).where(
            WhatsAppBroadcastRejectedContactModel.id == rejected_contact.id,
        )
    )
    group.recipient_opt_in_confirmed_at = group.recipient_opt_in_confirmed_at or now
    group.updated_at = now
    await session.flush()
    await suppress_active_replacement_recipients(
        session,
        agency_id=group.agency_id,
        broadcast_group_ids=[group.id],
        now=now,
    )
    await session.flush()
    await reconcile_mobile_passenger_access_for_broadcast(
        session,
        agency_id=group.agency_id,
        broadcast_group_id=group.id,
        actor_user_id=current_user.id,
    )
    return await _group_detail(session, group)
