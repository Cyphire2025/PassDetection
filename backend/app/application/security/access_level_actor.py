"""Keep request access levels when a mutation refreshes its real actor."""

from __future__ import annotations

import uuid
from dataclasses import replace

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.repositories.user_repository import UserRepository


def actual_user_role(user: User) -> UserRole:
    return UserRole(getattr(user, "actual_role", None) or user.role)


def actual_user_agency_id(user: User) -> uuid.UUID | None:
    return user.actual_agency_id if getattr(user, "actual_role", None) is not None else user.agency_id


def revalidate_access_level_actor(snapshot: User, refreshed: User) -> User:
    """Reapply a restricted role only after checking the current real identity."""

    if (
        refreshed.id != snapshot.id
        or not refreshed.is_active
        or refreshed.credential_state != "active"
        or refreshed.role != actual_user_role(snapshot)
        or refreshed.agency_id != actual_user_agency_id(snapshot)
        or refreshed.session_version != snapshot.session_version
    ):
        raise AuthorizationError("Your account permissions changed. Sign in again and retry.")
    if snapshot.actual_role is None:
        return refreshed
    if refreshed.role != UserRole.SUPER_ADMIN or snapshot.role not in {
        UserRole.AGENCY_MANAGER,
        UserRole.AGENCY_STAFF,
        UserRole.AGENCY_COORDINATOR,
    }:
        raise AuthorizationError("This account cannot switch access levels")
    return replace(
        refreshed,
        role=snapshot.role,
        agency_id=snapshot.agency_id,
        actual_role=refreshed.role,
        actual_agency_id=refreshed.agency_id,
        access_level_agency_name=snapshot.access_level_agency_name,
    )


async def refresh_access_level_actor(session: AsyncSession, snapshot: User) -> User:
    """Read current credential/session state after the caller locks the user row."""

    refreshed = await UserRepository(session).get_by_id(snapshot.id)
    if refreshed is None:
        raise AuthorizationError("Your account is no longer available")
    return revalidate_access_level_actor(snapshot, refreshed)
