"""
List Upload Links Use Case
==========================
"""

from __future__ import annotations

import uuid

from app.application.dtos.client_group_dtos import (
    ClientGroupOutputDTO,
    client_group_output_from_entity,
)
from app.domain.entities.entities import User
from app.domain.repositories.interfaces import IClientGroupRepository


class ListClientGroupsUseCase:
    """Lists all upload links for an agency."""

    def __init__(self, client_group_repository: IClientGroupRepository) -> None:
        self._client_group_repo = client_group_repository

    async def execute(
        self,
        agency_id: uuid.UUID,
        skip: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
    ) -> list[ClientGroupOutputDTO]:
        links = await self._client_group_repo.list_by_agency(
            agency_id,
            skip=skip,
            limit=limit,
            status_filter=status_filter,
            created_by_user_id=created_by_user_id,
            visible_to_user=visible_to_user,
        )
        return [
            client_group_output_from_entity(link)
            for link in links
        ]
