"""Access for upload links; HTTP declarations remain in client_groups."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import (
    ClientGroup,
    User,
    UserRole,
)
from app.domain.exceptions.exceptions import (
    AuthorizationError,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    PlatformSettingModel,
)
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.presentation.dependencies.auth import (
    WHATSAPP_BROADCAST_ROLES,
)

_CLIENT_GROUP_CREATION_ROLES = {
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
}
_PLATFORM_SETTINGS_KEY = "global"


def _owner_scope_for(user: User) -> uuid.UUID | None:
    return user.id if user.role == UserRole.AGENCY_STAFF else None


def _require_whatsapp_broadcast_access(user: User) -> None:
    if user.role not in WHATSAPP_BROADCAST_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="WhatsApp broadcast access is not available for this account.",
        )


async def _require_client_group_creation_access(user: User, session: AsyncSession) -> None:
    """Apply the server-authoritative role and manager feature policy."""

    if user.role not in _CLIENT_GROUP_CREATION_ROLES:
        raise AuthorizationError("This account cannot create upload links")
    if user.role != UserRole.AGENCY_MANAGER:
        return

    result = await session.execute(
        select(PlatformSettingModel.value).where(PlatformSettingModel.key == _PLATFORM_SETTINGS_KEY)
    )
    values = result.scalar_one_or_none() or {}
    if values.get("allow_manager_group_creation", True) is not True:
        raise AuthorizationError("Manager upload-link creation is disabled by platform settings")


async def _require_managed_group(
    session: AsyncSession, current_user: User, link_id: uuid.UUID, *, lock: bool
) -> ClientGroup:
    group = await ClientGroupRepository(session).get_by_id(link_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client group was not found",
        )
    try:
        await AuthorizationPolicy(session).require_manage_group(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc
    if lock:
        await session.execute(
            select(ClientGroupModel.id)
            .where(
                ClientGroupModel.id == group.id,
                ClientGroupModel.agency_id == group.agency_id,
            )
            .with_for_update()
        )
    return group


async def _require_viewable_group(
    session: AsyncSession, current_user: User, link_id: uuid.UUID
) -> ClientGroup:
    group = await ClientGroupRepository(session).get_by_id(link_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client group was not found",
        )
    try:
        await AuthorizationPolicy(session).require_view_group(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc
    return group
