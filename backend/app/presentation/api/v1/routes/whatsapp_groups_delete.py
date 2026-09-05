"""Whatsapp: groups delete."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.passenger_change_propagation import (
    reconcile_mobile_passenger_access_for_group,
)
from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    PassportRosterResolutionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.whatsapp_scope import _prepare_private_recipient_mutation
from app.presentation.api.v1.routes.whatsapp_shared import WHATSAPP_ROLES, _agency_filter
from app.presentation.dependencies.auth import require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.delete(
    "/groups/{group_id}",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(require_cookie_csrf)],
)
async def delete_broadcast_group(
    group_id: uuid.UUID,
    current_user: User = Depends(require_role(WHATSAPP_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, bool]:
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
    active_replacement_result = await session.execute(
        select(PassportRosterResolutionModel.id)
        .join(
            WhatsAppBroadcastRecipientModel,
            WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id
            == PassportRosterResolutionModel.id,
        )
        .where(
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
            PassportRosterResolutionModel.status == "active",
            PassportRosterResolutionModel.resolution_type == "replacement",
        )
        .limit(1)
    )
    if active_replacement_result.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This broadcast contains a person marked as replaced in a "
                "linked passport group. Restore that replacement before "
                "deleting the broadcast."
            ),
        )
    processing_result = await session.execute(
        select(func.count())
        .select_from(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.broadcast_group_id == group.id,
            WhatsAppRecipientMessageStateModel.status == "processing",
        )
    )
    explicit_processing_result = await session.execute(
        select(func.count())
        .select_from(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.broadcast_group_id == group.id,
            WhatsAppMessageLogModel.is_explicit_resend.is_(True),
            WhatsAppMessageLogModel.status == "processing",
        )
    )
    if int(processing_result.scalar_one()) > 0 or int(explicit_processing_result.scalar_one()) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A WhatsApp provider request is currently in progress. "
                "Wait for it to finish before deleting this broadcast."
            ),
        )
    await _prepare_private_recipient_mutation(
        session,
        agency_id=group.agency_id,
        broadcast_group_id=group.id,
        cancellation_reason=(
            "WhatsApp broadcast was deleted before private document or QR delivery"
        ),
    )
    now = datetime.now(tz=UTC)
    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.broadcast_group_id == group.id,
            WhatsAppMessageLogModel.status == "queued",
        )
        .values(
            status="failed",
            status_updated_at=now,
            error_message="WhatsApp broadcast deleted before delivery",
        )
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.broadcast_group_id == group.id,
            WhatsAppRecipientMessageStateModel.status == "queued",
        )
        .values(
            status="failed",
            batch_id=None,
            status_updated_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    linked_client_group_ids = tuple(
        sorted(
            set(
                (
                    await session.execute(
                        select(ClientGroupWhatsAppBroadcastLinkModel.client_group_id).where(
                            ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
                            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id == group.id,
                        )
                    )
                ).scalars()
            ),
            key=str,
        )
    )
    await session.execute(
        delete(WhatsAppBroadcastGroupModel).where(WhatsAppBroadcastGroupModel.id == group.id)
    )
    await session.flush()
    for linked_client_group_id in linked_client_group_ids:
        await reconcile_mobile_passenger_access_for_group(
            session,
            agency_id=group.agency_id,
            group_id=linked_client_group_id,
            actor_user_id=current_user.id,
        )
    return {"deleted": True}
