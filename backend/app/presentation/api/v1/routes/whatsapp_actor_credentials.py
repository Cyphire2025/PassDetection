"""Refresh credential authority while the caller holds the actual account lock."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.access_level_actor import refresh_access_level_actor
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import UserSecurityStateModel


async def refresh_locked_whatsapp_credentials(
    session: AsyncSession,
    current_user: User,
) -> User:
    """Retain canonical legacy/effective-role behavior with current security state."""
    # The existing parent account lock serializes creation of a legacy state row.
    # Refresh identity-map state before the canonical repository projects it.
    result = await session.execute(
        select(UserSecurityStateModel)
        .where(UserSecurityStateModel.user_id == current_user.id)
        .with_for_update(of=UserSecurityStateModel)
        .execution_options(populate_existing=True)
    )
    result.scalar_one_or_none()
    try:
        return await refresh_access_level_actor(session, current_user)
    except AuthorizationError as exc:
        raise HTTPException(
            403, "Your account is no longer authorized for WhatsApp broadcasts."
        ) from exc
