"""Locked management-scope lookup and workforce role contracts."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    UserModel,
)

ACCOUNT_ADMIN_ROLES = [UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER]
STAFF_ADMIN_ROLES = [UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER]
MANAGED_ROLES = (
    UserRole.AGENCY_MANAGER.value,
    UserRole.AGENCY_STAFF.value,
    UserRole.AGENCY_COORDINATOR.value,
)
LISTED_ACCOUNT_ROLES = (UserRole.AGENCY_STAFF.value, UserRole.AGENCY_COORDINATOR.value)


async def _get_manageable_account(
    session: AsyncSession,
    current_user: User,
    account_id: uuid.UUID,
) -> tuple[UserModel, str | None]:
    result = await session.execute(
        select(UserModel, AgencyModel.name.label("agency_name"))
        .outerjoin(AgencyModel, AgencyModel.id == UserModel.agency_id)
        .where(
            UserModel.id == account_id,
            UserModel.role.in_(MANAGED_ROLES),
            UserModel.deleted_at.is_(None),
        )
        .with_for_update(of=UserModel)
    )
    row = result.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Managed account was not found"
        )
    account, agency_name = row
    if current_user.role == UserRole.SUPER_ADMIN:
        return account, agency_name
    if account.agency_id != current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account is outside your management scope"
        )
    if current_user.role in (UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER) and account.role in {
        UserRole.AGENCY_STAFF.value,
        UserRole.AGENCY_COORDINATOR.value,
    }:
        return account, agency_name
    if current_user.role == UserRole.AGENCY_MANAGER and account.id == current_user.id:
        return account, agency_name
    if current_user.role == UserRole.AGENCY_ADMIN and account.role == UserRole.AGENCY_MANAGER.value:
        return account, agency_name
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Account is outside your management scope"
    )
