"""
Audit Log Repository
====================
Durable audit trail for security and operational actions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import AuditLogModel


class AuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        action: str,
        entity_type: str,
        agency_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        actor_email: str | None = None,
        entity_id: str | None = None,
        ip_address: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLogModel:
        model = AuditLogModel(
            id=uuid.uuid4(),
            agency_id=agency_id,
            user_id=user_id,
            actor_email=actor_email,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            ip_address=ip_address,
            metadata_json=metadata or {},
            created_at=datetime.now(tz=UTC),
        )
        self._session.add(model)
        await self._session.flush()
        return model

    async def list_by_agency(
        self,
        agency_id: uuid.UUID | None,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> list[AuditLogModel]:
        stmt = select(AuditLogModel)
        if agency_id is not None:
            stmt = stmt.where(AuditLogModel.agency_id == agency_id)
        stmt = stmt.order_by(AuditLogModel.created_at.desc()).offset(skip).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
