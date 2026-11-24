"""GC administration tenant lookup, locked context and audit boundaries."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.gc_mobile_models import (
    ClientManagerProfileModel,
    ClientOrganizationModel,
    GCGroupAccessModel,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    UserModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.presentation.api.v1.routes import gc_app_account_support as _account_support
from app.presentation.security.client_ip import trusted_client_ip

GC_ADMIN_ROLES = [UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER]


MobileAudience = Literal["passenger", "client_manager", "coordinator"]


def _tenant_id(current_user: User, requested: uuid.UUID | None = None) -> uuid.UUID:
    if current_user.role == UserRole.SUPER_ADMIN:
        if requested is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="agency_id is required for super-admin GC App operations",
            )
        return requested
    if current_user.agency_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The account is not assigned to an agency",
        )
    if requested is not None and requested != current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Agency scope mismatch")
    return current_user.agency_id


async def _get_group(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    *,
    lock: bool,
) -> ClientGroupModel:
    stmt = select(ClientGroupModel).where(
        ClientGroupModel.id == group_id,
        ClientGroupModel.agency_id == agency_id,
    )
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    group = (await session.execute(stmt)).scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return group


async def _get_group_access(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    *,
    lock: bool,
    include_removed: bool = False,
) -> GCGroupAccessModel:
    stmt = select(GCGroupAccessModel).where(
        GCGroupAccessModel.agency_id == agency_id,
        GCGroupAccessModel.group_id == group_id,
    )
    if not include_removed:
        stmt = stmt.where(GCGroupAccessModel.removed_at.is_(None))
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    access = (await session.execute(stmt)).scalar_one_or_none()
    if access is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GC App group not found")
    return access


async def _get_organization(
    session: AsyncSession,
    agency_id: uuid.UUID,
    organization_id: uuid.UUID,
    *,
    lock: bool,
) -> ClientOrganizationModel:
    stmt = select(ClientOrganizationModel).where(
        ClientOrganizationModel.id == organization_id,
        ClientOrganizationModel.agency_id == agency_id,
        ClientOrganizationModel.status == "active",
    )
    if lock:
        stmt = stmt.with_for_update()
    organization = (await session.execute(stmt)).scalar_one_or_none()
    if organization is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return organization


async def _get_client_manager(
    session: AsyncSession,
    agency_id: uuid.UUID,
    profile_id: uuid.UUID,
    *,
    lock: bool,
) -> tuple[ClientManagerProfileModel, UserModel, ClientOrganizationModel]:
    stmt = (
        select(ClientManagerProfileModel, UserModel, ClientOrganizationModel)
        .join(UserModel, UserModel.id == ClientManagerProfileModel.user_id)
        .join(
            ClientOrganizationModel,
            ClientOrganizationModel.id == ClientManagerProfileModel.organization_id,
        )
        .where(
            ClientManagerProfileModel.id == profile_id,
            ClientManagerProfileModel.agency_id == agency_id,
            ClientManagerProfileModel.deleted_at.is_(None),
            UserModel.role == UserRole.CLIENT_MANAGER.value,
            UserModel.agency_id == agency_id,
        )
    )
    if lock:
        # Lock every selected base row so the account/profile/organization
        # authorization context cannot change during the mutation.
        stmt = stmt.with_for_update()
    row = (await session.execute(stmt)).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client Manager not found"
        )
    profile, user, organization = row
    return profile, user, organization


def _require_revision(current: int, expected: int) -> None:
    if current != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Client Manager changed; refresh and retry",
        )


async def _audit(
    session: AsyncSession,
    actor: User,
    request: Request,
    *,
    agency_id: uuid.UUID,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID,
    metadata: dict[str, object] | None,
) -> None:
    await AuditLogRepository(session).record(
        action=action,
        entity_type=entity_type,
        agency_id=agency_id,
        user_id=actor.id,
        actor_email=actor.email,
        entity_id=str(entity_id),
        ip_address=trusted_client_ip(request),
        metadata=metadata,
    )


_integrity_constraint_name = _account_support.integrity_constraint_name


_client_manager_duplicate_message = _account_support.client_manager_duplicate_message


_organization_response = _account_support.organization_response


_client_manager_response = _account_support.client_manager_response


_organization_status = _account_support.organization_status


_client_manager_status = _account_support.client_manager_status
