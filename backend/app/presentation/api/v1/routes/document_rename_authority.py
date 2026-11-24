"""Current actor and tenant boundaries for document rename."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.application.security.access_level_actor import (
    actual_user_agency_id,
    actual_user_role,
    refresh_access_level_actor,
)
from app.application.use_cases.document_rename.read_scope import (
    DocumentRenameScopeError,
    rename_agency,
)
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    UserModel,
)
from app.infrastructure.repositories.document_rename_queries import (
    rename_batch_filters,
)


def _ensure_allowed(current_user: User) -> uuid.UUID:
    try:
        return rename_agency(current_user)
    except DocumentRenameScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        ) from exc


async def _lock_active_rename_actor(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    agency_id: uuid.UUID,
    expected_role: UserRole,
    current_user: User | None = None,
) -> UserModel | User:
    """Re-authorize the unchanged actor role and agency under row locks."""

    actual_agency_id = (
        actual_user_agency_id(current_user) if current_user is not None else agency_id
    )
    actual_role = actual_user_role(current_user) if current_user is not None else expected_role
    result = await session.execute(
        select(UserModel)
        .join(AgencyModel, AgencyModel.id == agency_id)
        .where(
            UserModel.id == user_id,
            UserModel.agency_id == actual_agency_id
            if actual_agency_id is not None
            else UserModel.agency_id.is_(None),
            UserModel.is_active.is_(True),
            UserModel.deleted_at.is_(None),
            UserModel.role == actual_role.value,
            AgencyModel.is_active.is_(True),
        )
        .with_for_update(of=(UserModel, AgencyModel))  # type: ignore[arg-type]
        .execution_options(populate_existing=True)
    )
    actor = result.scalar_one_or_none()
    if actor is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account or agency is no longer authorized for document rename.",
        )
    if current_user is not None and getattr(current_user, "actual_role", None) is not None:
        return await refresh_access_level_actor(session, current_user)
    return actor


def _batch_filters_for_identity(
    *,
    user_id: uuid.UUID,
    role: UserRole | str,
    agency_id: uuid.UUID,
) -> list[ColumnElement[bool]]:
    return rename_batch_filters(user_id=user_id, role=role, agency_id=agency_id)


def _batch_filters(
    current_user: User,
    agency_id: uuid.UUID,
) -> list[ColumnElement[bool]]:
    return _batch_filters_for_identity(
        user_id=current_user.id,
        role=current_user.role,
        agency_id=agency_id,
    )
