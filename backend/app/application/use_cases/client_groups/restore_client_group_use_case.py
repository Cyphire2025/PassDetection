"""
Restore Client Group Use Case
=============================
Restores an archived client group back to active workflows.
"""

from __future__ import annotations

import uuid

from app.application.dtos.client_group_dtos import ClientGroupOutputDTO
from app.domain.exceptions.exceptions import AuthorizationError, EntityNotFoundError
from app.domain.repositories.interfaces import IClientGroupRepository


class RestoreClientGroupUseCase:
    def __init__(self, client_group_repository: IClientGroupRepository) -> None:
        self._client_group_repo = client_group_repository

    async def execute(
        self,
        group_id: uuid.UUID,
        agency_id: uuid.UUID,
        *,
        created_by_user_id: uuid.UUID | None = None,
    ) -> ClientGroupOutputDTO:
        group = await self._client_group_repo.get_by_id(group_id)
        if not group:
            raise EntityNotFoundError("ClientGroup", str(group_id))
        if group.agency_id != agency_id:
            raise AuthorizationError("Cannot restore a group belonging to another agency")
        if created_by_user_id and group.created_by_user_id != created_by_user_id:
            raise AuthorizationError("Cannot restore a group created by another manager")

        group.restore()
        await self._client_group_repo.update(group)
        return ClientGroupOutputDTO(
            id=group.id,
            name=group.name,
            token=group.token,
            agency_id=group.agency_id,
            status=group.status.value,
            created_by_user_id=group.created_by_user_id,
            created_at=group.created_at,
            closed_at=group.closed_at,
        )
