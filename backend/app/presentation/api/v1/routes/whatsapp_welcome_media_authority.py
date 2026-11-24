"""Hold current broadcast authority for the owned provider media operation."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.access_level_actor import revalidate_access_level_actor
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import (
    AgencyModel,
    UserModel,
    UserSecurityStateModel,
    WhatsAppBroadcastGroupModel,
)
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.whatsapp_archive_policy import require_active_broadcast
from app.presentation.api.v1.routes.whatsapp_shared import _agency_filter


async def _require_current_media_scope(
    session: AsyncSession,
    current_user: User,
    group_id: uuid.UUID,
) -> None:
    # Match account mutation order: actor, credential/session state, agency, target.
    actor = await session.scalar(
        select(UserModel)
        .where(UserModel.id == current_user.id)
        .with_for_update(of=UserModel)
        .execution_options(populate_existing=True),
    )
    if actor is None or actor.deleted_at is not None:
        raise HTTPException(403, "Your account is no longer authorized for WhatsApp broadcasts.")
    security_state = await session.scalar(
        select(UserSecurityStateModel)
        .where(UserSecurityStateModel.user_id == current_user.id)
        .with_for_update()
        .execution_options(populate_existing=True),
    )
    try:
        refreshed = revalidate_access_level_actor(
            current_user,
            UserRepository._to_entity(actor, security_state),
        )
    except AuthorizationError as exc:
        raise HTTPException(403, str(exc)) from exc
    if refreshed.agency_id is not None:
        agency_id = await session.scalar(
            select(AgencyModel.id)
            .where(
                AgencyModel.id == refreshed.agency_id,
                AgencyModel.is_active.is_(True),
            )
            .with_for_update(),
        )
        if agency_id is None:
            raise HTTPException(
                403, "Your account is no longer authorized for WhatsApp broadcasts."
            )
    group = await session.scalar(
        select(WhatsAppBroadcastGroupModel)
        .where(
            WhatsAppBroadcastGroupModel.id == group_id,
            *_agency_filter(refreshed),
        )
        .with_for_update()
        .execution_options(populate_existing=True),
    )
    if group is None:
        raise HTTPException(404, "WhatsApp broadcast group not found")
    require_active_broadcast(group)


@asynccontextmanager
async def authorized_welcome_media_upload(
    session: AsyncSession,
    current_user: User,
    group_id: uuid.UUID,
) -> AsyncIterator[None]:
    """Acquire fresh authority after validation and release all read locks on exit."""
    try:
        await _require_current_media_scope(session, current_user, group_id)
        yield
    finally:
        await session.rollback()
