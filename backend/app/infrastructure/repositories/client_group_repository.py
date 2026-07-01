"""
SQLAlchemy Upload Link Repository
=================================
Concrete implementation of IClientGroupRepository.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging.logger import get_logger
from app.domain.entities.entities import ClientGroup, GroupStatus
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.domain.repositories.interfaces import IClientGroupRepository
from app.infrastructure.database.models import ClientGroupModel

logger = get_logger(__name__)


class ClientGroupRepository(IClientGroupRepository):
    """SQLAlchemy implementation of IClientGroupRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_entity(model: ClientGroupModel) -> ClientGroup:
        return ClientGroup(
            id=model.id,
            name=model.name,
            token=model.token,
            agency_id=model.agency_id,
            status=GroupStatus(model.status),
            created_by_user_id=model.created_by_user_id,
            created_at=model.created_at,
            closed_at=model.closed_at,
        )

    @staticmethod
    def _to_model(entity: ClientGroup) -> ClientGroupModel:
        return ClientGroupModel(
            id=entity.id,
            name=entity.name,
            token=entity.token,
            agency_id=entity.agency_id,
            status=entity.status.value,
            created_by_user_id=entity.created_by_user_id,
            created_at=entity.created_at,
            closed_at=entity.closed_at,
        )

    async def get_by_id(self, link_id: uuid.UUID) -> ClientGroup | None:
        result = await self._session.execute(
            select(ClientGroupModel).where(ClientGroupModel.id == link_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_token(self, token: str) -> ClientGroup | None:
        result = await self._session.execute(
            select(ClientGroupModel).where(ClientGroupModel.token == token)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def save(self, link: ClientGroup) -> ClientGroup:
        model = self._to_model(link)
        self._session.add(model)
        await self._session.flush()
        logger.info("client_group_created", group_id=str(link.id), group_name=link.name)
        return link

    async def update(self, link: ClientGroup) -> ClientGroup:
        result = await self._session.execute(
            select(ClientGroupModel).where(ClientGroupModel.id == link.id)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise EntityNotFoundError("ClientGroup", str(link.id))

        model.name = link.name
        model.token = link.token
        model.agency_id = link.agency_id
        model.status = link.status.value
        model.closed_at = link.closed_at

        await self._session.flush()
        return link

    async def list_by_agency(
        self,
        agency_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
        created_by_user_id: uuid.UUID | None = None,
    ) -> list[ClientGroup]:
        stmt = select(ClientGroupModel).where(ClientGroupModel.agency_id == agency_id)
        if status_filter:
            stmt = stmt.where(ClientGroupModel.status == status_filter)
        else:
            stmt = stmt.where(ClientGroupModel.status != GroupStatus.ARCHIVED.value)
        if created_by_user_id:
            stmt = stmt.where(ClientGroupModel.created_by_user_id == created_by_user_id)
        stmt = stmt.order_by(ClientGroupModel.created_at.desc()).offset(skip).limit(limit)
        result = await self._session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def count_active_by_agency(
        self,
        agency_id: uuid.UUID,
        *,
        created_by_user_id: uuid.UUID | None = None,
    ) -> int:
        from sqlalchemy import func
        stmt = (
            select(func.count()).select_from(ClientGroupModel).where(
                ClientGroupModel.agency_id == agency_id,
                ClientGroupModel.status == GroupStatus.ACTIVE.value,
            )
        )
        if created_by_user_id:
            stmt = stmt.where(ClientGroupModel.created_by_user_id == created_by_user_id)

        result = await self._session.execute(stmt)
        return result.scalar_one()
