"""
Create Upload Link Use Case
===========================
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from app.application.dtos.client_group_dtos import CreateClientGroupInputDTO, ClientGroupOutputDTO
from app.core.logging.logger import get_logger
from app.domain.entities.entities import ClientGroup
from app.domain.repositories.interfaces import IClientGroupRepository

logger = get_logger(__name__)


class CreateClientGroupUseCase:
    """Generates a secure, time-limited passport upload link for a client."""

    def __init__(self, client_group_repository: IClientGroupRepository) -> None:
        self._client_group_repo = client_group_repository

    async def execute(
        self,
        dto: CreateClientGroupInputDTO,
        agency_id: uuid.UUID,
        created_by_user_id: uuid.UUID,
    ) -> ClientGroupOutputDTO:
        # Generate cryptographically secure unguessable token
        token = secrets.token_urlsafe(32)

        # Create Domain Entity
        link = ClientGroup.create(
            name=dto.name,
            token=token,
            agency_id=agency_id,
            created_by_user_id=created_by_user_id,
        )

        # Save to DB
        await self._client_group_repo.save(link)

        logger.info(
            "client_group_created",
            group_id=str(link.id),
            agency_id=str(agency_id),
            group_name=dto.name,
        )

        return ClientGroupOutputDTO(
            id=link.id,
            name=link.name,
            token=link.token,
            agency_id=link.agency_id,
            status=link.status.value,
            created_by_user_id=link.created_by_user_id,
            created_at=link.created_at,
            closed_at=link.closed_at,
        )
