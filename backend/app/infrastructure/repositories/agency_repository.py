"""
SQLAlchemy Agency Repository
============================
Concrete implementation of IAgencyRepository.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging.logger import get_logger
from app.domain.entities.entities import Agency
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.domain.repositories.interfaces import IAgencyRepository
from app.infrastructure.database.models import AgencyModel

logger = get_logger(__name__)


class AgencyRepository(IAgencyRepository):
    """SQLAlchemy implementation of IAgencyRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_entity(model: AgencyModel) -> Agency:
        return Agency(
            id=model.id,
            name=model.name,
            email=model.email,
            phone=model.phone,
            is_active=model.is_active,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    @staticmethod
    def _to_model(entity: Agency) -> AgencyModel:
        return AgencyModel(
            id=entity.id,
            name=entity.name,
            email=entity.email,
            phone=entity.phone,
            is_active=entity.is_active,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    async def get_by_id(self, agency_id: uuid.UUID) -> Agency | None:
        result = await self._session.execute(
            select(AgencyModel).where(AgencyModel.id == agency_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_email(self, email: str) -> Agency | None:
        result = await self._session.execute(
            select(AgencyModel).where(AgencyModel.email == email.lower().strip())
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def save(self, agency: Agency) -> Agency:
        model = self._to_model(agency)
        self._session.add(model)
        await self._session.flush()
        logger.info("agency_created", agency_id=str(agency.id), name=agency.name)
        return agency

    async def update(self, agency: Agency) -> Agency:
        result = await self._session.execute(
            select(AgencyModel).where(AgencyModel.id == agency.id)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise EntityNotFoundError("Agency", str(agency.id))

        model.name = agency.name
        model.email = agency.email
        model.phone = agency.phone
        model.is_active = agency.is_active
        model.updated_at = agency.updated_at

        await self._session.flush()
        return agency

    async def list_all(self, *, skip: int = 0, limit: int = 50) -> list[Agency]:
        result = await self._session.execute(
            select(AgencyModel)
            .offset(skip)
            .limit(limit)
        )
        return [self._to_entity(m) for m in result.scalars().all()]
