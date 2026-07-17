"""
Get Upload Link By Token Use Case
=================================
"""

from __future__ import annotations

from app.application.dtos.client_group_dtos import (
    ClientGroupOutputDTO,
    client_group_output_from_entity,
)
from app.domain.entities.entities import GroupStatus
from app.domain.exceptions.exceptions import (
    EntityNotFoundError,
    GroupClosedError,
    ValidationError,
)
from app.domain.repositories.interfaces import IClientGroupRepository


class GetClientGroupByTokenUseCase:
    """Retrieves and validates an upload link by its token."""

    def __init__(self, client_group_repository: IClientGroupRepository) -> None:
        self._client_group_repo = client_group_repository

    async def execute(self, token: str) -> ClientGroupOutputDTO:
        link = await self._client_group_repo.get_by_token(token)
        if not link:
            raise EntityNotFoundError("ClientGroup", token)

        # Validate status
        if not link.is_active():
            if link.status == GroupStatus.CLOSED:
                raise GroupClosedError()
            else:
                raise ValidationError("Upload link is not active")

        return client_group_output_from_entity(link)
