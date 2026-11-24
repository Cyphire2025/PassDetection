"""Validated workforce account and group response projections."""

from __future__ import annotations

from typing import Literal, cast

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    ClientGroupModel,
    ManagerGroupAccessModel,
    UserModel,
    UserSecurityStateModel,
)
from app.presentation.api.v1.routes.admin_account_scope import REMOVED_GROUP_STATUSES
from app.presentation.api.v1.schemas.operations_schemas import (
    ManagerGroupAccessResponse,
    ManagerResponse,
)

_CredentialState = Literal["invited", "active"]


def _validated_credential_state(value: str) -> _CredentialState:
    if value not in {"invited", "active"}:
        raise RuntimeError("Invalid persisted workforce credential state.")
    return cast(_CredentialState, value)


def _group_response(group: ClientGroupModel) -> ManagerGroupAccessResponse:
    return ManagerGroupAccessResponse(
        id=group.id,
        agency_id=group.agency_id,
        name=group.name,
        status=group.status,
        created_by_user_id=group.created_by_user_id,
    )


async def _manager_response(session: AsyncSession, manager: UserModel) -> ManagerResponse:
    groups_result = await session.execute(
        select(ClientGroupModel).where(
            ClientGroupModel.agency_id == manager.agency_id,
            ClientGroupModel.status.notin_(REMOVED_GROUP_STATUSES),
            or_(
                ClientGroupModel.created_by_user_id == manager.id,
                ClientGroupModel.id.in_(
                    select(ManagerGroupAccessModel.group_id).where(
                        ManagerGroupAccessModel.manager_id == manager.id
                    )
                ),
            ),
        )
    )
    groups = list(groups_result.scalars().all())
    access_result = await session.execute(
        select(ManagerGroupAccessModel).where(ManagerGroupAccessModel.manager_id == manager.id)
    )
    access_group_ids = {row.group_id for row in access_result.scalars().all()}
    security_state = (
        await session.execute(
            select(UserSecurityStateModel).where(UserSecurityStateModel.user_id == manager.id)
        )
    ).scalar_one_or_none()
    return ManagerResponse(
        id=manager.id,
        full_name=manager.full_name,
        email=manager.email,
        role=manager.role,
        agency_id=manager.agency_id,
        is_active=manager.is_active,
        created_at=manager.created_at,
        last_login_at=manager.last_login_at,
        created_groups=[
            _group_response(group) for group in groups if group.created_by_user_id == manager.id
        ],
        assigned_groups=[
            _group_response(group) for group in groups if group.id in access_group_ids
        ],
        credential_state=(
            _validated_credential_state(security_state.credential_state)
            if security_state
            else "active"
        ),
    )
