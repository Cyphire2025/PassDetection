"""Client group and qualifier selection persistence contracts."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod

from app.domain.entities.entities import ClientGroup, QualifierSelection, User


class IClientGroupRepository(ABC):
    """Contract for upload link persistence operations."""

    async def require_active_company(
        self, agency_id: uuid.UUID, company_id: uuid.UUID
    ) -> dict[str, object]:
        """Validate and lock the active company until the group transaction ends."""
        raise NotImplementedError

    @abstractmethod
    async def get_by_id(self, link_id: uuid.UUID) -> ClientGroup | None: ...

    @abstractmethod
    async def get_by_token(self, token: str) -> ClientGroup | None: ...

    @abstractmethod
    async def save(self, link: ClientGroup) -> ClientGroup: ...

    @abstractmethod
    async def update(self, link: ClientGroup) -> ClientGroup: ...

    @abstractmethod
    async def list_by_agency(
        self,
        agency_id: uuid.UUID,
        *,
        skip: int = 0,
        limit: int = 50,
        status_filter: str | None = None,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
    ) -> list[ClientGroup]: ...

    @abstractmethod
    async def count_active_by_agency(
        self,
        agency_id: uuid.UUID,
        *,
        created_by_user_id: uuid.UUID | None = None,
        visible_to_user: User | None = None,
    ) -> int: ...


class IQualifierSelectionRepository(ABC):
    """Contract for short-lived public qualifier selections."""

    @abstractmethod
    async def get_by_token_hash(
        self,
        group_id: uuid.UUID,
        token_hash: str,
        *,
        for_update: bool = False,
    ) -> QualifierSelection | None: ...

    @abstractmethod
    async def save(self, selection: QualifierSelection) -> QualifierSelection: ...

    @abstractmethod
    async def get_submission_id(
        self,
        selection_id: uuid.UUID,
    ) -> uuid.UUID | None: ...
