"""Whatsapp: scope."""

from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.whatsapp.message_templates import WhatsAppMessageType
from app.core.config.settings import get_settings
from app.domain.entities.entities import User
from app.infrastructure.database.models import (
    AgencyModel,
    UserModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.whatsapp.private_delivery_policy import (
    PrivateDeliveryMutationBlocked,
    prepare_private_delivery_identity_mutation,
)
from app.presentation.api.v1.routes.whatsapp_shared import _agency_filter


async def _prepare_private_recipient_mutation(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    broadcast_group_id: uuid.UUID,
    recipient_id: uuid.UUID | None = None,
    cancellation_reason: str,
) -> None:
    """Cancel queued private sends and block indeterminate provider states."""

    try:
        await prepare_private_delivery_identity_mutation(
            session,
            agency_id=agency_id,
            broadcast_group_ids={broadcast_group_id},
            recipient_ids={recipient_id} if recipient_id else None,
            cancel_queued=True,
            cancellation_reason=cancellation_reason,
        )
    except PrivateDeliveryMutationBlocked as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


async def _lock_active_whatsapp_actor(
    session: AsyncSession,
    *,
    current_user: User,
    require_agency: bool,
) -> UserModel:
    """Re-authorize the actor after untrusted workbook parsing.

    Authentication and role dependencies read the user before the route starts,
    which opens a database transaction. Workbook bytes must be read and parsed
    only after that transaction is released. The write transaction therefore
    re-fetches and locks the actor (and their agency when agency scope is
    required) so deactivation, role changes, reassignment, or agency suspension
    during parsing fail closed before any roster mutation.
    """

    expected_agency_id = current_user.agency_id
    expected_role = current_user.role.value
    predicates = [
        UserModel.id == current_user.id,
        UserModel.role == expected_role,
        UserModel.is_active.is_(True),
        UserModel.deleted_at.is_(None),
    ]
    statement = select(UserModel).where(*predicates)
    if require_agency:
        if expected_agency_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Your account is no longer authorized for WhatsApp broadcasts.",
            )
        statement = (
            select(UserModel)
            .join(AgencyModel, AgencyModel.id == UserModel.agency_id)
            .where(
                *predicates,
                UserModel.agency_id == expected_agency_id,
                AgencyModel.is_active.is_(True),
            )
            .with_for_update()
        )
    else:
        statement = statement.with_for_update(of=UserModel)

    result = await session.execute(statement.execution_options(populate_existing=True))
    actor = result.scalar_one_or_none()
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is no longer authorized for WhatsApp broadcasts.",
        )
    return actor


async def _release_auth_transaction(
    session: AsyncSession = Depends(get_db_session),
) -> None:
    """End the read-only authentication transaction before CPU/file work."""

    await session.rollback()


def _configured_template_name(message_type: WhatsAppMessageType) -> str:
    settings = get_settings()
    if message_type == "welcome":
        return settings.whatsapp_welcome_template_name
    if message_type == "reminder":
        return settings.whatsapp_reminder_template_name
    return settings.whatsapp_passport_link_template_name


async def _lock_removable_broadcast_recipient(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    recipient_id: uuid.UUID,
    current_user: User,
) -> tuple[WhatsAppBroadcastGroupModel, WhatsAppBroadcastRecipientModel]:
    """Lock a tenant-owned broadcast parent before its recipient child."""

    group_result = await session.execute(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(current_user),
        )
        .with_for_update()
    )
    group = group_result.scalar_one_or_none()
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp recipient not found",
        )

    recipient_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.id == recipient_id,
            WhatsAppBroadcastRecipientModel.broadcast_group_id == group.id,
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
        .with_for_update()
    )
    recipient = recipient_result.scalar_one_or_none()
    if recipient is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="WhatsApp recipient not found",
        )
    return group, recipient
