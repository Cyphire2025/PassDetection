"""User and agency persistence contracts."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from app.domain.entities.entities import Agency, User


class IUserRepository(ABC):
    """Contract for user persistence operations."""

    @abstractmethod
    async def get_by_id(self, user_id: uuid.UUID) -> User | None: ...

    @abstractmethod
    async def get_by_email(self, email: str) -> User | None: ...

    @abstractmethod
    async def save(self, user: User) -> User: ...

    @abstractmethod
    async def update(self, user: User) -> User: ...

    @abstractmethod
    async def delete(self, user_id: uuid.UUID) -> None: ...

    @abstractmethod
    async def list_by_agency(
        self, agency_id: uuid.UUID, *, skip: int = 0, limit: int = 50
    ) -> list[User]: ...


class IAgencyRepository(ABC):
    """Contract for agency persistence operations."""

    @abstractmethod
    async def get_by_id(self, agency_id: uuid.UUID) -> Agency | None: ...

    @abstractmethod
    async def get_by_email(self, email: str) -> Agency | None: ...

    @abstractmethod
    async def save(self, agency: Agency) -> Agency: ...

    @abstractmethod
    async def update(self, agency: Agency) -> Agency: ...

    @abstractmethod
    async def list_all(self, *, skip: int = 0, limit: int = 50) -> list[Agency]: ...
