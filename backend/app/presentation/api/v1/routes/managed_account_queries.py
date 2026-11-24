"""Managed workforce and staff listing endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.managed_account_scope import (
    ACCOUNT_ADMIN_ROLES,
    LISTED_ACCOUNT_ROLES,
    STAFF_ADMIN_ROLES,
)
from app.presentation.api.v1.routes.managed_account_values import _account_response
from app.presentation.api.v1.schemas.operations_schemas import (
    ManagedAccountResponse,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()


@router.get(
    "",
    response_model=list[ManagedAccountResponse],
    summary="List accounts within the caller's management scope",
)
async def list_managed_accounts(
    current_user: User = Depends(require_role(ACCOUNT_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[ManagedAccountResponse]:
    filters: list[ColumnElement[bool]] = [
        UserModel.role.in_(LISTED_ACCOUNT_ROLES),
        UserModel.deleted_at.is_(None),
    ]
    if current_user.role == UserRole.AGENCY_ADMIN:
        filters.append(UserModel.agency_id == current_user.agency_id)
    elif current_user.role == UserRole.AGENCY_MANAGER:
        filters.extend(
            [
                UserModel.role == UserRole.AGENCY_COORDINATOR.value,
                UserModel.agency_id == current_user.agency_id,
            ]
        )
    result = await session.execute(
        select(UserModel, AgencyModel.name.label("agency_name"), UserSecurityStateModel)
        .outerjoin(AgencyModel, AgencyModel.id == UserModel.agency_id)
        .outerjoin(UserSecurityStateModel, UserSecurityStateModel.user_id == UserModel.id)
        .where(*filters)
        .order_by(UserModel.role.asc(), UserModel.created_at.desc())
    )
    return [
        _account_response(account, agency_name, security_state)
        for account, agency_name, security_state in result.all()
    ]


@router.get("/staff", response_model=list[ManagedAccountResponse], summary="List staff accounts")
async def list_staff_accounts(
    current_user: User = Depends(require_role(STAFF_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[ManagedAccountResponse]:
    filters = [
        UserModel.role == UserRole.AGENCY_STAFF.value,
        UserModel.deleted_at.is_(None),
    ]
    if current_user.role != UserRole.SUPER_ADMIN:
        filters.append(UserModel.agency_id == current_user.agency_id)
    result = await session.execute(
        select(UserModel, AgencyModel.name.label("agency_name"), UserSecurityStateModel)
        .outerjoin(AgencyModel, AgencyModel.id == UserModel.agency_id)
        .outerjoin(UserSecurityStateModel, UserSecurityStateModel.user_id == UserModel.id)
        .where(*filters)
        .order_by(UserModel.created_at.desc())
    )
    return [
        _account_response(account, agency_name, security_state)
        for account, agency_name, security_state in result.all()
    ]
