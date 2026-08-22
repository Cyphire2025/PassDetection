"""
Create Upload Link Use Case
===========================
"""

from __future__ import annotations

import secrets
import uuid

from app.application.dtos.client_group_dtos import (
    ClientGroupOutputDTO,
    CreateClientGroupInputDTO,
    client_group_output_from_entity,
)
from app.application.platform_policies import PlatformPolicyProvider
from app.core.logging.logger import get_logger
from app.domain.entities.entities import ClientGroup, GroupStatus
from app.domain.repositories.interfaces import IClientGroupRepository

logger = get_logger(__name__)


class CreateClientGroupUseCase:
    """Generates a secure, time-limited passport upload link for a client."""

    def __init__(
        self,
        client_group_repository: IClientGroupRepository,
        platform_policy_provider: PlatformPolicyProvider | None = None,
    ) -> None:
        self._client_group_repo = client_group_repository
        self._platform_policy_provider = platform_policy_provider

    async def execute(
        self,
        dto: CreateClientGroupInputDTO,
        agency_id: uuid.UUID,
        created_by_user_id: uuid.UUID,
    ) -> ClientGroupOutputDTO:
        # Existing direct callers keep the historical ACTIVE default. Runtime
        # HTTP construction injects the persisted platform policy provider.
        initial_status = GroupStatus.ACTIVE
        if self._platform_policy_provider is not None:
            policies = await self._platform_policy_provider.load()
            initial_status = GroupStatus(policies.default_group_status)

        # Generate cryptographically secure unguessable token
        token = secrets.token_urlsafe(32)

        # Create Domain Entity
        link = ClientGroup.create(
            name=dto.name,
            token=token,
            agency_id=agency_id,
            created_by_user_id=created_by_user_id,
            destination=dto.destination,
            travel_date=dto.travel_date,
            return_date=dto.return_date,
            timezone=dto.timezone,
            package_name=dto.package_name,
            departure_cities=dto.departure_cities,
            base_city_enabled=dto.base_city_enabled,
            nearest_international_airport_enabled=dto.nearest_international_airport_enabled,
            staff_code_enabled=dto.staff_code_enabled,
            agent_employee_code_enabled=dto.agent_employee_code_enabled,
            meal_preference_enabled=dto.meal_preference_enabled,
            require_selfie=dto.require_selfie,
            allow_files_from_device=dto.allow_files_from_device,
            ask_nearest_domestic_airport=dto.ask_nearest_domestic_airport,
            relation_with_qualifier_enabled=(
                dto.relation_with_qualifier_enabled
            ),
            designation_enabled=dto.designation_enabled,
            agency_dealership_name_enabled=(
                dto.agency_dealership_name_enabled
            ),
            custom_questions=dto.custom_questions,
            custom_details=dto.custom_details,
            notes=dto.notes,
            initial_status=initial_status,
            passport_retention_days=(
                policies.passport_data_retention_days
                if self._platform_policy_provider is not None
                else None
            ),
        )

        # Save to DB
        await self._client_group_repo.save(link)

        logger.info(
            "client_group_created",
            group_id=str(link.id),
            agency_id=str(agency_id),
        )

        return client_group_output_from_entity(link)
