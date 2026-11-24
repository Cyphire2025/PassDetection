"""Bulk passport actor: focused scope, mutation or transaction owner."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.access_level_actor import (
    actual_user_agency_id,
    actual_user_role,
    refresh_access_level_actor,
    revalidate_access_level_actor,
)
from app.domain.entities.entities import (
    User,
)
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import (
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.repositories.user_repository import UserRepository


async def _lock_active_bulk_approval_actor(
    session: AsyncSession,
    current_user: User,
) -> User:
    """Revalidate the unchanged bulk-approval actor under a row lock."""

    actual_agency_id = actual_user_agency_id(current_user)
    agency_filter = (
        UserModel.agency_id.is_(None)
        if actual_agency_id is None
        else UserModel.agency_id == actual_agency_id
    )
    result = await session.execute(
        select(UserModel)
        .where(
            UserModel.id == current_user.id,
            UserModel.role == actual_user_role(current_user).value,
            agency_filter,
            UserModel.is_active.is_(True),
            UserModel.deleted_at.is_(None),
        )
        .with_for_update(of=UserModel)
        .execution_options(populate_existing=True)
    )
    actor_model = result.scalar_one_or_none()
    if actor_model is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account permissions changed. Sign in again and retry.",
        )
    # Keep the parent-user then security-state lock order used by credential
    # resets. A legacy account with no state row still uses active/version1.
    security_state = (
        await session.execute(
            select(UserSecurityStateModel)
            .where(UserSecurityStateModel.user_id == current_user.id)
            .with_for_update(of=UserSecurityStateModel)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()
    if getattr(current_user, "actual_role", None) is not None:
        return await refresh_access_level_actor(session, current_user)
    try:
        return revalidate_access_level_actor(
            current_user, UserRepository._to_entity(actor_model, security_state)
        )
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message) from exc


_lock_active_bulk_approval_actor.__module__ = (
    "app.presentation.api.v1.routes.passport_routes.bulk_actions"
)
