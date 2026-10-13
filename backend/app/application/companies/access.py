"""Shared company authorization for the directory and historical projections."""

from __future__ import annotations

import uuid
from typing import cast

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import (
    AuthorizationError,
    EntityNotFoundError,
    ValidationError,
)
from app.infrastructure.database.gc_mobile_models import ClientOrganizationModel
from app.infrastructure.database.models import ClientGroupModel

COMPANY_ADMIN_ROLES = (UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER)
COMPANY_LOOKUP_ROLES = (*COMPANY_ADMIN_ROLES, UserRole.AGENCY_STAFF)


def company_agency_scope(user: User, requested: uuid.UUID | None = None) -> uuid.UUID:
    if user.role == UserRole.SUPER_ADMIN:
        if requested is None:
            raise ValidationError("Select an agency for this operation", field="agency_id")
        return requested
    if user.agency_id is None or (requested is not None and requested != user.agency_id):
        raise AuthorizationError("Agency scope mismatch")
    return user.agency_id


async def require_company(
    session: AsyncSession, *, user: User, company_id: uuid.UUID,
    agency_id: uuid.UUID | None = None, lock: bool = False,
) -> ClientOrganizationModel:
    """Company-wide history never follows from membership or minimal lookup."""
    if user.role not in COMPANY_ADMIN_ROLES:
        raise AuthorizationError()
    scope = company_agency_scope(user, agency_id)
    stmt = select(ClientOrganizationModel).where(
        ClientOrganizationModel.id == company_id,
        ClientOrganizationModel.agency_id == scope,
        ClientOrganizationModel.status != "deleted",
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    company = await session.scalar(stmt)
    if company is None:
        raise EntityNotFoundError("Company", company_id)
    return company


def visible_company_groups(user: User, agency_id: uuid.UUID, company_id: uuid.UUID) -> Select[tuple[ClientGroupModel]]:
    """One exact population for summary totals, groups and participation history."""
    return cast(Select[tuple[ClientGroupModel]], AuthorizationPolicy.apply_group_visibility_scope(
        select(ClientGroupModel).where(
            ClientGroupModel.agency_id == agency_id,
            ClientGroupModel.company_id == company_id,
            ClientGroupModel.status.in_(("active", "closed", "archived")),
            ClientGroupModel.deleted_at.is_(None),
        ), user,
    ))
