"""Canonical tenant scope/counters and bounded ECR metadata projections."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthorizationError
from app.infrastructure.database.ecr_models import EcrBatchModel, EcrItemModel
from app.infrastructure.database.models import AgencyModel

ECR_ALLOWED_ROLES = {
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
}
ECR_COUNT_FIELDS = (
    "total_count",
    "processed_count",
    "ecr_count",
    "na_count",
    "review_count",
    "failed_count",
)


def ecr_scope(user: User) -> list[ColumnElement[bool]]:
    if not user.agency_id or user.role not in ECR_ALLOWED_ROLES:
        raise AuthorizationError("Insufficient permissions")
    filters = [
        EcrBatchModel.agency_id == user.agency_id,
        select(AgencyModel.id)
        .where(AgencyModel.id == user.agency_id, AgencyModel.is_active.is_(True))
        .exists(),
    ]
    if user.role == UserRole.AGENCY_STAFF:
        filters.append(EcrBatchModel.created_by_user_id == user.id)
    return filters


async def ecr_item_counts(
    session: AsyncSession, batch_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, int]]:
    if not batch_ids:
        return {}
    rows = (
        await session.execute(
            select(
                EcrItemModel.batch_id,
                func.count().label("total_count"),
                func.sum(
                    case((EcrItemModel.status.in_(["completed", "failed"]), 1), else_=0)
                ).label("processed_count"),
                func.sum(case((EcrItemModel.result == "ECR", 1), else_=0)).label("ecr_count"),
                func.sum(case((EcrItemModel.result == "NA", 1), else_=0)).label("na_count"),
                func.sum(case((EcrItemModel.result == "NEEDS_REVIEW", 1), else_=0)).label(
                    "review_count"
                ),
                func.sum(case((EcrItemModel.status == "failed", 1), else_=0)).label("failed_count"),
            )
            .where(EcrItemModel.batch_id.in_(batch_ids))
            .group_by(EcrItemModel.batch_id)
        )
    ).mappings()
    return {row["batch_id"]: {key: int(row[key]) for key in ECR_COUNT_FIELDS} for row in rows}


class ECRReadRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def active_agency(self, user: User) -> bool:
        ecr_scope(user)
        return (
            await self.session.scalar(
                select(AgencyModel.id)
                .where(
                    AgencyModel.id == user.agency_id,
                    AgencyModel.is_active.is_(True),
                )
                .with_for_update(read=True)
            )
            is not None
        )

    @staticmethod
    def _batch_columns() -> tuple[Any, ...]:
        model = EcrBatchModel
        return (
            model.id.label("batch_id"),
            func.substr(model.title, 1, 161).label("title"),
            model.status,
            model.expected_count,
            model.created_at,
        )

    async def batches(
        self, actor: User, *, size: int, cutoff: datetime, after: tuple[datetime, uuid.UUID] | None
    ) -> list[dict[str, Any]]:
        model = EcrBatchModel
        statement = select(*self._batch_columns()).where(
            *ecr_scope(actor), model.created_at <= cutoff
        )
        if after:
            statement = statement.where(
                or_(
                    model.created_at < after[0],
                    and_(model.created_at == after[0], model.id < after[1]),
                )
            )
        rows = (
            (
                await self.session.execute(
                    statement.order_by(model.created_at.desc(), model.id.desc()).limit(size + 1)
                )
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows]

    async def batch(self, actor: User, identifier: uuid.UUID) -> dict[str, Any] | None:
        row = (
            (
                await self.session.execute(
                    select(*self._batch_columns()).where(
                        EcrBatchModel.id == identifier, *ecr_scope(actor)
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row else None

    async def items(
        self,
        actor: User,
        identifier: uuid.UUID,
        *,
        size: int,
        cutoff: datetime,
        after: tuple[datetime, uuid.UUID] | None,
    ) -> list[dict[str, Any]]:
        model = EcrItemModel
        statement = (
            select(
                model.id,
                model.client_id,
                func.substr(model.original_filename, 1, 256).label("original_filename"),
                model.status,
                model.result,
                func.substr(model.reason, 1, 256).label("reason"),
                model.created_at,
            )
            .join(EcrBatchModel, EcrBatchModel.id == model.batch_id)
            .where(model.batch_id == identifier, *ecr_scope(actor), model.created_at <= cutoff)
        )
        if after:
            statement = statement.where(
                or_(
                    model.created_at > after[0],
                    and_(model.created_at == after[0], model.id > after[1]),
                )
            )
        rows = (
            (
                await self.session.execute(
                    statement.order_by(model.created_at, model.id).limit(size + 1)
                )
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows]
