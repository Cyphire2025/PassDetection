"""Current identity and tenant/group locks for code-owned additive operations."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.operations import MCPDatabaseContext, MCPOperationError
from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.models import AgencyModel, ClientGroupModel, UserModel
from app.infrastructure.repositories.user_repository import UserRepository


async def require_change_actor(context: MCPDatabaseContext, agency_id: uuid.UUID | None) -> User:
    actor = await UserRepository(context.session).get_by_id(context.principal.user_id)
    retained = await context.session.scalar(
        select(UserModel.id).where(
            UserModel.id == context.principal.user_id,
            UserModel.deleted_at.is_(None),
        )
    )
    if (
        actor is None
        or retained is None
        or not actor.is_active
        or actor.role != UserRole.SUPER_ADMIN
    ):
        raise MCPAuthError("access_denied", 403)
    if agency_id is not None:
        agency = await context.session.scalar(
            select(AgencyModel)
            .where(
                AgencyModel.id == agency_id,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if agency is None or not agency.is_active:
            raise MCPOperationError("office_agency_unavailable")
    return actor


async def require_change_group(
    context: MCPDatabaseContext,
    actor: User,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    *,
    exclusive: bool = False,
) -> ClientGroupModel:
    group = await context.session.scalar(
        select(ClientGroupModel)
        .where(
            ClientGroupModel.id == group_id,
            ClientGroupModel.agency_id == agency_id,
            ClientGroupModel.status != "deleted",
            ClientGroupModel.deleted_at.is_(None),
        )
        .with_for_update(read=not exclusive)
        .execution_options(populate_existing=True)
    )
    if group is None:
        raise MCPOperationError("office_group_unavailable")
    try:
        await AuthorizationPolicy(context.session).require_view_group(actor, group)
    except AuthorizationError as exc:
        raise MCPAuthError("access_denied", 403) from exc
    return group
