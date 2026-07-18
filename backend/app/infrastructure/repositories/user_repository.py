"""
SQLAlchemy User Repository
==========================
Concrete implementation of IUserRepository.
Translates between SQLAlchemy ORM models and domain entities.

Design:
  - All DB interactions go through this class — no raw SQL in use cases.
  - Maps ORM models → domain entities and vice versa.
  - Raises domain exceptions, not SQLAlchemy exceptions.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging.logger import get_logger
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.domain.repositories.interfaces import IUserRepository
from app.infrastructure.database.models import UserModel

logger = get_logger(__name__)


class UserRepository(IUserRepository):
    """SQLAlchemy implementation of IUserRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Mapping ───────────────────────────────────────────────────────────────

    @staticmethod
    def _to_entity(model: UserModel) -> User:
        return User(
            id=model.id,
            email=model.email,
            hashed_password=model.hashed_password,
            full_name=model.full_name,
            role=UserRole(model.role),
            agency_id=model.agency_id,
            is_active=model.is_active,
            created_at=model.created_at,
            updated_at=model.updated_at,
            last_login_at=model.last_login_at,
        )

    @staticmethod
    def _to_model(entity: User) -> UserModel:
        return UserModel(
            id=entity.id,
            email=entity.email,
            hashed_password=entity.hashed_password,
            full_name=entity.full_name,
            role=entity.role.value,
            agency_id=entity.agency_id,
            is_active=entity.is_active,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            last_login_at=entity.last_login_at,
        )

    # ── IUserRepository Implementation ────────────────────────────────────────

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.email == email.lower().strip())
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def save(self, user: User) -> User:
        model = self._to_model(user)
        self._session.add(model)
        await self._session.flush()
        logger.info("user_created", user_id=str(user.id))
        return user

    async def update(self, user: User) -> User:
        result = await self._session.execute(
            select(UserModel).where(UserModel.id == user.id)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise EntityNotFoundError("User", str(user.id))

        model.email           = user.email
        model.hashed_password = user.hashed_password
        model.full_name       = user.full_name
        model.role            = user.role.value
        model.agency_id       = user.agency_id
        model.is_active       = user.is_active
        model.updated_at      = user.updated_at
        model.last_login_at   = user.last_login_at

        await self._session.flush()
        return user

    async def delete(self, user_id: uuid.UUID) -> None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.id == user_id)
        )
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            await self._session.flush()

    async def list_by_agency(
        self, agency_id: uuid.UUID, *, skip: int = 0, limit: int = 50
    ) -> list[User]:
        result = await self._session.execute(
            select(UserModel)
            .where(UserModel.agency_id == agency_id)
            .offset(skip)
            .limit(limit)
        )
        return [self._to_entity(m) for m in result.scalars().all()]
