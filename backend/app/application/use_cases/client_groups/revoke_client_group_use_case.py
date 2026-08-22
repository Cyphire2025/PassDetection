"""
Revoke Upload Link Use Case
===========================
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


class RevokeClientGroupUseCase:
    """Manually revokes a secure upload link."""

    def __init__(
        self,
        client_group_repository: IClientGroupRepository,
        platform_policy_provider: PlatformPolicyProvider | None = None,
    ) -> None:
        self._client_group_repo = client_group_repository
        self._platform_policy_provider = platform_policy_provider

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
        policies = (
            await self._platform_policy_provider.load()
            if self._platform_policy_provider is not None
            else None
        )
        link.close(
            passport_retention_days=(
                policies.passport_data_retention_days if policies is not None else None
            )
        )

        # Update persistent state
        await self._client_group_repo.update(link)

        return client_group_output_from_entity(link)
