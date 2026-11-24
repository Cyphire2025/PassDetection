"""Client-manager group validation and bounded assignment projection."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.gc_mobile_models import (
    ClientManagerGroupAssignmentModel,
    ClientOrganizationModel,
    GCGroupAccessModel,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
)
from app.presentation.api.v1.schemas.gc_app_schemas import (
    ClientManagerAssignedGroupResponse,
)


async def _validate_manager_groups(
    session: AsyncSession,
    agency_id: uuid.UUID,
    organization_id: uuid.UUID,
    group_ids: list[uuid.UUID],
) -> dict[uuid.UUID, GCGroupAccessModel]:
    unique_ids = list(dict.fromkeys(group_ids))
    if not unique_ids:
        return {}
    accesses = list(
        (
            await session.execute(
                select(GCGroupAccessModel).where(
                    GCGroupAccessModel.agency_id == agency_id,
                    GCGroupAccessModel.group_id.in_(unique_ids),
                    GCGroupAccessModel.client_organization_id == organization_id,
                )
            )
        ).scalars()
    )
    by_group = {item.group_id: item for item in accesses}
    if len(by_group) != len(unique_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Every assigned group must belong to the selected organization in GC App",
        )
    return by_group


async def _manager_group_map(
    session: AsyncSession, profile_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[ClientManagerAssignedGroupResponse]]:
    if not profile_ids:
        return {}
    rows = (
        await session.execute(
            select(
                ClientManagerGroupAssignmentModel.profile_id,
                ClientGroupModel,
                GCGroupAccessModel,
                ClientOrganizationModel,
            )
            .join(
                GCGroupAccessModel,
                GCGroupAccessModel.id == ClientManagerGroupAssignmentModel.gc_group_access_id,
            )
            .join(
                ClientGroupModel,
                ClientGroupModel.id == ClientManagerGroupAssignmentModel.group_id,
            )
            .join(
                ClientOrganizationModel,
                ClientOrganizationModel.id == ClientManagerGroupAssignmentModel.organization_id,
            )
            .where(
                ClientManagerGroupAssignmentModel.profile_id.in_(profile_ids),
                ClientManagerGroupAssignmentModel.is_active.is_(True),
                ClientManagerGroupAssignmentModel.revoked_at.is_(None),
                GCGroupAccessModel.agency_id == ClientManagerGroupAssignmentModel.agency_id,
                ClientGroupModel.agency_id == ClientManagerGroupAssignmentModel.agency_id,
                ClientOrganizationModel.agency_id == ClientManagerGroupAssignmentModel.agency_id,
            )
            .order_by(ClientGroupModel.travel_date.asc(), ClientGroupModel.name.asc())
        )
    ).all()
    result: dict[uuid.UUID, list[ClientManagerAssignedGroupResponse]] = {}
    for profile_id, group, access, organization in rows:
        result.setdefault(profile_id, []).append(
            ClientManagerAssignedGroupResponse(
                id=group.id,
                name=group.name,
                destination=group.destination,
                travel_date=group.travel_date,
                return_date=group.return_date,
                lifecycle_status=group.status,
                gc_enabled=access.is_enabled and access.revoked_at is None,
                client_organization_id=organization.id,
                client_organization_name=organization.name,
            )
        )
    return result
