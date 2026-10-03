"""Refresh a dashboard mutation actor under its current account row fence."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.access_level_actor import (
    actual_user_agency_id,
    actual_user_role,
    refresh_access_level_actor,
)
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthorizationError
from app.domain.exceptions.travel_tracker import TravelTrackerError
from app.infrastructure.database.models import UserModel
from app.infrastructure.repositories.user_repository import UserRepository


async def lock_tracker_actor(session: AsyncSession, snapshot: User) -> User:
    agency_id = actual_user_agency_id(snapshot)
    agency_filter = (
        UserModel.agency_id.is_(None) if agency_id is None else UserModel.agency_id == agency_id
    )
    result = await session.execute(
        select(UserModel)
        .where(
            UserModel.id == snapshot.id,
            UserModel.role == actual_user_role(snapshot).value,
            agency_filter,
            UserModel.is_active.is_(True),
            UserModel.deleted_at.is_(None),
        )
        .with_for_update(of=UserModel)
        .execution_options(populate_existing=True)
    )
    actor = result.scalar_one_or_none()
    if actor is None:
        raise TravelTrackerError(
            status_code=403, detail="Your account permissions changed. Sign in again and retry."
        )
    if snapshot.actual_role is not None:
        try:
            return await refresh_access_level_actor(session, snapshot)
        except AuthorizationError as exc:
            raise TravelTrackerError(status_code=403, detail=str(exc)) from exc
    return UserRepository._to_entity(actor)
