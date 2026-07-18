"""
SQLAlchemy Upload Link Repository
=================================
Concrete implementation of IClientGroupRepository.
"""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.authorization_policy import AuthorizationPolicy
from app.core.logging.logger import get_logger
from app.domain.entities.entities import ClientGroup, GroupStatus, User
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.domain.repositories.interfaces import IClientGroupRepository
from app.infrastructure.database.models import ClientGroupModel, ManagerGroupAccessModel

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
            destination=model.destination,
            travel_date=model.travel_date,
            return_date=model.return_date,
            package_name=model.package_name,
            departure_cities=list(model.departure_cities or []),
            base_city_enabled=model.base_city_enabled,
            nearest_international_airport_enabled=model.nearest_international_airport_enabled,
            staff_code_enabled=model.staff_code_enabled,
            meal_preference_enabled=model.meal_preference_enabled,
            require_selfie=model.require_selfie,
            allow_files_from_device=model.allow_files_from_device,
            ask_nearest_domestic_airport=model.ask_nearest_domestic_airport,
            relation_with_qualifier_enabled=model.relation_with_qualifier_enabled,
            notes=model.notes,
            deleted_at=model.deleted_at,
            deleted_passport_count=model.deleted_passport_count,
            deletion_retained_records=model.deletion_retained_records,
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
            destination=entity.destination,
            travel_date=entity.travel_date,
            return_date=entity.return_date,
            package_name=entity.package_name,
            departure_cities=entity.departure_cities,
            base_city_enabled=entity.base_city_enabled,
            nearest_international_airport_enabled=entity.nearest_international_airport_enabled,
            staff_code_enabled=entity.staff_code_enabled,
            meal_preference_enabled=entity.meal_preference_enabled,
            require_selfie=entity.require_selfie,
            allow_files_from_device=entity.allow_files_from_device,
            ask_nearest_domestic_airport=entity.ask_nearest_domestic_airport,
            relation_with_qualifier_enabled=entity.relation_with_qualifier_enabled,
            notes=entity.notes,
            deleted_at=entity.deleted_at,
            deleted_passport_count=entity.deleted_passport_count,
            deletion_retained_records=entity.deletion_retained_records,
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

    async def manager_can_access(self, group_id: uuid.UUID, manager_id: uuid.UUID) -> bool:
        result = await self._session.execute(
            select(ClientGroupModel.id)
            .outerjoin(
                ManagerGroupAccessModel,
                (ManagerGroupAccessModel.group_id == ClientGroupModel.id)
                & (ManagerGroupAccessModel.manager_id == manager_id),
            )
            .where(
                ClientGroupModel.id == group_id,
                or_(
                    ClientGroupModel.created_by_user_id == manager_id,
                    ManagerGroupAccessModel.manager_id == manager_id,
                ),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def save(self, link: ClientGroup) -> ClientGroup:
        model = self._to_model(link)
        self._session.add(model)
        await self._session.flush()
        logger.info("client_group_created", group_id=str(link.id))
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
        model.destination = link.destination
        model.travel_date = link.travel_date
        model.return_date = link.return_date
        model.package_name = link.package_name
        model.departure_cities = link.departure_cities
        model.base_city_enabled = link.base_city_enabled
        model.nearest_international_airport_enabled = link.nearest_international_airport_enabled
        model.staff_code_enabled = link.staff_code_enabled
        model.meal_preference_enabled = link.meal_preference_enabled
        model.require_selfie = link.require_selfie
        model.allow_files_from_device = link.allow_files_from_device
        model.ask_nearest_domestic_airport = link.ask_nearest_domestic_airport
        model.relation_with_qualifier_enabled = link.relation_with_qualifier_enabled
        model.notes = link.notes
        model.deleted_at = link.deleted_at
        model.deleted_passport_count = link.deleted_passport_count
        model.deletion_retained_records = link.deletion_retained_records

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
        visible_to_user: User | None = None,
    ) -> list[ClientGroup]:
        stmt = select(ClientGroupModel).where(ClientGroupModel.agency_id == agency_id)
        if status_filter:
            stmt = stmt.where(ClientGroupModel.status == status_filter)
        else:
            stmt = stmt.where(ClientGroupModel.status.notin_([GroupStatus.ARCHIVED.value, GroupStatus.DELETED.value]))
        if created_by_user_id:
            stmt = stmt.outerjoin(
                ManagerGroupAccessModel,
                (ManagerGroupAccessModel.group_id == ClientGroupModel.id)
                & (ManagerGroupAccessModel.manager_id == created_by_user_id),
            ).where(
                or_(
                    ClientGroupModel.created_by_user_id == created_by_user_id,
                    ManagerGroupAccessModel.manager_id == created_by_user_id,
                )
            )
        if visible_to_user:
            stmt = AuthorizationPolicy.apply_group_visibility_scope(stmt, visible_to_user)
        stmt = stmt.order_by(ClientGroupModel.created_at.desc()).offset(skip).limit(limit)
        result = await self._session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def count_active_by_agency(
        self,
        agency_id: uuid.UUID,
        *,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
    ) -> int:
        from sqlalchemy import func
        stmt = (
            select(func.count()).select_from(ClientGroupModel).where(
                ClientGroupModel.agency_id == agency_id,
                ClientGroupModel.status == GroupStatus.ACTIVE.value,
            )
        )
        if created_by_user_id:
            stmt = stmt.outerjoin(
                ManagerGroupAccessModel,
                (ManagerGroupAccessModel.group_id == ClientGroupModel.id)
                & (ManagerGroupAccessModel.manager_id == created_by_user_id),
            ).where(
                or_(
                    ClientGroupModel.created_by_user_id == created_by_user_id,
                    ManagerGroupAccessModel.manager_id == created_by_user_id,
                )
            )
        if visible_to_user:
            stmt = AuthorizationPolicy.apply_group_visibility_scope(stmt, visible_to_user)

        result = await self._session.execute(stmt)
        return result.scalar_one()
