"""Lock current actor and export scope after externally controlled import work."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.access_level_actor import refresh_access_level_actor
from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import ClientGroup, User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import (
    ClientGroupModel,
    ManagerGroupAccessModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository


async def lock_document_import_authority(
    session: AsyncSession,
    current_user: User,
    group: ClientGroup,
) -> User:
    """Keep the existing export policy and legacy/effective-role actor rules."""
    account = (
        await session.execute(
            select(UserModel)
            .where(
                UserModel.id == current_user.id,
                UserModel.is_active.is_(True),
                UserModel.deleted_at.is_(None),
            )
            .with_for_update(of=UserModel)
            .execution_options(populate_existing=True),
        )
    ).scalar_one_or_none()
    if account is None:
        raise HTTPException(403, "Your account permissions changed. Sign in again and retry.")
    # The parent lock also serializes creation of state for a legacy account.
    (
        await session.execute(
            select(UserSecurityStateModel)
            .where(UserSecurityStateModel.user_id == current_user.id)
            .with_for_update(of=UserSecurityStateModel)
            .execution_options(populate_existing=True),
        )
    ).scalar_one_or_none()
    try:
        actor = await refresh_access_level_actor(session, current_user)
    except AuthorizationError as exc:
        raise HTTPException(403, exc.message) from exc
    locked_group = (
        await session.execute(
            select(ClientGroupModel)
            .where(
                ClientGroupModel.id == group.id,
                ClientGroupModel.agency_id == group.agency_id,
            )
            .with_for_update(of=ClientGroupModel)
            .execution_options(populate_existing=True),
        )
    ).scalar_one_or_none()
    if locked_group is None:
        raise HTTPException(403, "This passport group is no longer available.")
    if actor.role is UserRole.AGENCY_STAFF and locked_group.created_by_user_id != actor.id:
        await session.execute(
            select(ManagerGroupAccessModel)
            .where(
                ManagerGroupAccessModel.manager_id == actor.id,
                ManagerGroupAccessModel.group_id == group.id,
            )
            .with_for_update(of=ManagerGroupAccessModel)
            .execution_options(populate_existing=True)
        )
    try:
        await AuthorizationPolicy(session).require_export_data(actor, locked_group)
    except AuthorizationError as exc:
        raise HTTPException(403, exc.message) from exc
    return actor


async def _authorized_passport_document_group(
    group_id: uuid.UUID, current_user: User, session: AsyncSession
) -> ClientGroup:
    if not current_user.agency_id or current_user.role == UserRole.AGENCY_COORDINATOR:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )
    group = await ClientGroupRepository(session).get_by_id(group_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found"
        )
    try:
        await AuthorizationPolicy(session).require_export_data(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)
    return group


_authorized_passport_document_group.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.document_import"
)
