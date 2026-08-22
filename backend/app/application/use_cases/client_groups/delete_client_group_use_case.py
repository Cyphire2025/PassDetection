"""
Delete Client Group Use Case
============================
Soft-deletes a client group by archiving it.
"""

from __future__ import annotations

import uuid

from app.application.dtos.client_group_dtos import (
    ClientGroupOutputDTO,
    client_group_output_from_entity,
)
from app.application.platform_policies import PlatformPolicyProvider
from app.domain.exceptions.exceptions import AuthorizationError, EntityNotFoundError
from app.domain.repositories.interfaces import IClientGroupRepository


class DeleteClientGroupUseCase:
    """Archives a client group without deleting passport submission records."""

    def __init__(
        self,
        client_group_repository: IClientGroupRepository,
        platform_policy_provider: PlatformPolicyProvider | None = None,
    ) -> None:
        self._client_group_repo = client_group_repository
        self._platform_policy_provider = platform_policy_provider

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
            raise AuthorizationError("Cannot delete a group belonging to another agency")
        if created_by_user_id and group.created_by_user_id != created_by_user_id:
            raise AuthorizationError("Cannot archive a group created by another manager")

        policies = (
            await self._platform_policy_provider.load()
            if self._platform_policy_provider is not None
            else None
        )
        group.archive(
            passport_retention_days=(
                policies.passport_data_retention_days if policies is not None else None
            )
        )
        await self._client_group_repo.update(group)

        return client_group_output_from_entity(group)
