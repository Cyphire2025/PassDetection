"""Agency workforce group-access assignment endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.application.use_cases.client_groups.group_access import (
    assignable_group_predicates,
    explicit_access_group_ids,
)
from app.domain.entities.entities import (
    User,
    UserRole,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    ManagerGroupAccessModel,
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.admin_account_scope import (
    REMOVED_GROUP_STATUSES,
    _manager_scope,
    _staff_scope,
)
from app.presentation.api.v1.routes.admin_account_views import _group_response, _manager_response
from app.presentation.api.v1.schemas.operations_schemas import (
    AssignManagerGroupsRequest,
    ManagerGroupAccessResponse,
    ManagerResponse,
)
from app.presentation.dependencies.auth import require_recent_mfa, require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.get(
    "/groups",
    response_model=list[ManagerGroupAccessResponse],
    status_code=status.HTTP_200_OK,
    summary="List groups available for account access assignment",
)
async def list_admin_groups(
    current_user: User = Depends(
        require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER])
    ),
    session: AsyncSession = Depends(get_db_session),
) -> list[ManagerGroupAccessResponse]:
    filters: list[ColumnElement[bool]] = [ClientGroupModel.status.notin_(REMOVED_GROUP_STATUSES)]
    if current_user.role != UserRole.SUPER_ADMIN:
        filters.append(ClientGroupModel.agency_id == current_user.agency_id)
    result = await session.execute(
        select(ClientGroupModel).where(*filters).order_by(ClientGroupModel.created_at.desc())
    )
    return [_group_response(group) for group in result.scalars().all()]


@router.get(
    "/staff",
    response_model=list[ManagerResponse],
    status_code=status.HTTP_200_OK,
    summary="List staff accounts with group access",
)
async def list_staff_for_access(
    current_user: User = Depends(
        require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER])
    ),
    session: AsyncSession = Depends(get_db_session),
) -> list[ManagerResponse]:
    result = await session.execute(
        select(UserModel).where(*_staff_scope(current_user)).order_by(UserModel.created_at.desc())
    )
    return [await _manager_response(session, staff) for staff in result.scalars().all()]


@router.put(
    "/staff/{staff_id}/groups",
    response_model=ManagerResponse,
    status_code=status.HTTP_200_OK,
    summary="Replace a staff member's assigned group access",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def assign_staff_groups(
    staff_id: uuid.UUID,
    body: AssignManagerGroupsRequest,
    current_user: User = Depends(
        require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER])
    ),
    session: AsyncSession = Depends(get_db_session),
) -> ManagerResponse:
    staff_result = await session.execute(
        select(UserModel)
        .where(UserModel.id == staff_id, *_staff_scope(current_user))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    staff = staff_result.scalar_one_or_none()
    if not staff:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Staff account was not found"
        )
    if not staff.agency_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Staff account is not assigned to an agency",
        )

    group_ids = list(dict.fromkeys(body.group_ids))
    if group_ids:
        groups_result = await session.execute(
            select(ClientGroupModel).where(
                ClientGroupModel.id.in_(group_ids),
                *assignable_group_predicates(staff.agency_id),
            )
        )
        valid_groups = list(groups_result.scalars().all())
        valid_group_ids = {group.id for group in valid_groups}
        if valid_group_ids != set(group_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="One or more groups are not assignable to this staff member",
            )
        explicit_ids = set(explicit_access_group_ids(valid_groups, staff.id))
        group_ids = [group_id for group_id in group_ids if group_id in explicit_ids]

    await session.execute(
        delete(ManagerGroupAccessModel).where(ManagerGroupAccessModel.manager_id == staff.id)
    )
    for group_id in group_ids:
        session.add(
            ManagerGroupAccessModel(
                manager_id=staff.id,
                group_id=group_id,
                agency_id=staff.agency_id,
            )
        )
    await session.flush()
    return await _manager_response(session, staff)


@router.put(
    "/managers/{manager_id}/groups",
    response_model=ManagerResponse,
    status_code=status.HTTP_200_OK,
    summary="Replace a manager's extra assigned group access",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def assign_manager_groups(
    manager_id: uuid.UUID,
    body: AssignManagerGroupsRequest,
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> ManagerResponse:
    manager_result = await session.execute(
        select(UserModel)
        .where(UserModel.id == manager_id, *_manager_scope(current_user))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    manager = manager_result.scalar_one_or_none()
    if not manager:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager was not found")
    if not manager.agency_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Manager is not assigned to an agency"
        )

    group_ids = list(dict.fromkeys(body.group_ids))
    if group_ids:
        groups_result = await session.execute(
            select(ClientGroupModel).where(
                ClientGroupModel.id.in_(group_ids),
                *assignable_group_predicates(manager.agency_id),
            )
        )
        valid_groups = list(groups_result.scalars().all())
        valid_group_ids = {group.id for group in valid_groups}
        if valid_group_ids != set(group_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="One or more groups are not assignable to this manager",
            )
        explicit_ids = set(explicit_access_group_ids(valid_groups, manager.id))
        group_ids = [group_id for group_id in group_ids if group_id in explicit_ids]

    await session.execute(
        delete(ManagerGroupAccessModel).where(ManagerGroupAccessModel.manager_id == manager.id)
    )
    for group_id in group_ids:
        session.add(
            ManagerGroupAccessModel(
                manager_id=manager.id,
                group_id=group_id,
                agency_id=manager.agency_id,
            )
        )
    await session.flush()
    return await _manager_response(session, manager)
