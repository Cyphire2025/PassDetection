"""Refresh the dashboard actor before committing an owned common document."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.access_level_actor import revalidate_access_level_actor
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import UserModel, UserSecurityStateModel
from app.infrastructure.repositories.user_repository import UserRepository


async def require_current_common_document_actor(session: AsyncSession, snapshot: User) -> User:
    """Lock actor then credentials before the caller locks its group and access."""
    actor = await session.scalar(
        select(UserModel)
        .where(UserModel.id == snapshot.id)
        .with_for_update(of=UserModel)
        .execution_options(populate_existing=True),
    )
    if actor is None or actor.deleted_at is not None:
        raise HTTPException(403, "Your account is no longer authorized for GC App content.")
    security_state = await session.scalar(
        select(UserSecurityStateModel)
        .where(UserSecurityStateModel.user_id == snapshot.id)
        .with_for_update(of=UserSecurityStateModel)
        .execution_options(populate_existing=True),
    )
    # Mapping preserves the existing active/version-one defaults when a legacy
    # account has no security row. The locked parent also fences its insertion.
    try:
        return revalidate_access_level_actor(
            snapshot, UserRepository._to_entity(actor, security_state)
        )
    except AuthorizationError as exc:
        raise HTTPException(403, exc.message) from exc
