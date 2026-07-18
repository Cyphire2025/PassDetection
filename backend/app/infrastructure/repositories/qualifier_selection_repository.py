"""SQLAlchemy repository for public qualifier selections."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import QualifierSelection
from app.domain.repositories.interfaces import IQualifierSelectionRepository
from app.infrastructure.database.models import (
    PassportSubmissionModel,
    QualifierSelectionModel,
)


class QualifierSelectionRepository(IQualifierSelectionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_entity(model: QualifierSelectionModel) -> QualifierSelection:
        def aware(value: datetime) -> datetime:
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)

        return QualifierSelection(
            id=model.id,
            group_id=model.group_id,
            token_hash=model.token_hash,
            is_self=model.is_self,
            relation_code=model.relation_code,
            relation_label=model.relation_label,
            selected_at=aware(model.selected_at),
            expires_at=aware(model.expires_at),
            created_at=aware(model.created_at),
        )

    async def get_by_token_hash(
        self,
        group_id: uuid.UUID,
        token_hash: str,
        *,
        for_update: bool = False,
    ) -> QualifierSelection | None:
        stmt = select(QualifierSelectionModel).where(
            QualifierSelectionModel.group_id == group_id,
            QualifierSelectionModel.token_hash == token_hash,
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def save(self, selection: QualifierSelection) -> QualifierSelection:
        self._session.add(
            QualifierSelectionModel(
                id=selection.id,
                group_id=selection.group_id,
                token_hash=selection.token_hash,
                is_self=selection.is_self,
                relation_code=selection.relation_code,
                relation_label=selection.relation_label,
                selected_at=selection.selected_at,
                expires_at=selection.expires_at,
                created_at=selection.created_at,
            )
        )
        await self._session.flush()
        return selection

    async def get_submission_id(
        self,
        selection_id: uuid.UUID,
    ) -> uuid.UUID | None:
        result = await self._session.execute(
            select(PassportSubmissionModel.id)
            .where(
                PassportSubmissionModel.qualifier_selection_id == selection_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()
