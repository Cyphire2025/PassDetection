"""
Revoke Upload Link Use Case
===========================
"""

from __future__ import annotations

import uuid

from app.application.dtos.client_group_dtos import ClientGroupOutputDTO, client_group_output_from_entity
from app.domain.exceptions.exceptions import EntityNotFoundError, AuthorizationError
from app.domain.repositories.interfaces import IClientGroupRepository


class RevokeClientGroupUseCase:
    """Manually revokes a secure upload link."""

    def __init__(self, client_group_repository: IClientGroupRepository) -> None:
        self._client_group_repo = client_group_repository

    async def execute(
        self,
        link_id: uuid.UUID,
        agency_id: uuid.UUID,
        *,
        created_by_user_id: uuid.UUID | None = None,
    ) -> ClientGroupOutputDTO:
        link = await self._client_group_repo.get_by_id(link_id)
        if not link:
            raise EntityNotFoundError("ClientGroup", str(link_id))

        # Check if link belongs to the agency of the user attempting to revoke
        if link.agency_id != agency_id:
            raise AuthorizationError("Cannot revoke a link belonging to another agency")
        if created_by_user_id and link.created_by_user_id != created_by_user_id:
            raise AuthorizationError("Cannot close a link created by another manager")

        # Perform domain logic
        link.close()

        # Update persistent state
        await self._client_group_repo.update(link)

        return client_group_output_from_entity(link)
