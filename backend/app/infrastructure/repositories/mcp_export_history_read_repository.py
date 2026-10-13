"""Column-specific, byte-admitted checkpoint reads without object/file access."""

from __future__ import annotations

import uuid
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import LargeBinary, Text, and_, cast, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.application.use_cases.passports.export_changes import SUBMISSION_REVISION_FIELDS
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    ClientGroupModel,
    PassportExportHistoryModel,
    PassportSubmissionModel,
)
from app.infrastructure.repositories.passport_submission_repository import (
    PassportSubmissionRepository,
)

MAX_CHECKPOINT_PEOPLE = 5000


class HistorySourceLimit(ValueError):
    pass


class MCPExportHistoryReadRepository:
    def __init__(self, session: AsyncSession, byte_limit: int):
        self.session, self.remaining_bytes = session, byte_limit

    async def group(self, agency_id: uuid.UUID, group_id: uuid.UUID) -> Any:
        return (await self.session.execute(select(ClientGroupModel.id, ClientGroupModel.agency_id,
            ClientGroupModel.status, ClientGroupModel.deleted_at).where(ClientGroupModel.id == group_id,
            ClientGroupModel.agency_id == agency_id).with_for_update(read=True, nowait=True))).one_or_none()

    @staticmethod
    def scope(agency_id: uuid.UUID, group_id: uuid.UUID, owner: uuid.UUID | None = None) -> list[Any]:
        model = PassportExportHistoryModel
        predicates = [model.agency_id == agency_id, model.group_id == group_id,
                      model.status == "completed", model.format_version == 1]
        if owner is not None:
            predicates.append(model.created_by_user_id == owner)
        return predicates

    async def current_revision_sources(self, agency_id: uuid.UUID, group_id: uuid.UUID, actor: User) -> list[Any]:
        """One bounded roster, SHARE locked before byte admission and hydration.

        Only fields used by the canonical content digest enter memory. Images,
        rich ORM relationships and unrelated metadata are never loaded.
        """
        model = PassportSubmissionModel
        scope = PassportSubmissionRepository(self.session)._group_scope(
            agency_id, group_id, exclude_archived_groups=True, operational_only=True,
            visible_to_user=actor, created_by_user_id=actor.id if actor.role == UserRole.AGENCY_STAFF else None,
        )
        columns = [model.id, model.updated_at, *(getattr(model, field) for field in SUBMISSION_REVISION_FIELDS)]
        # Return only bounded UUIDs and byte counts while acquiring the row locks.
        # JSON stays in PostgreSQL until the entire locked roster is admitted.
        admitted = (await self.session.execute(scope.with_only_columns(
            model.id, self._byte_size(columns).label("source_bytes"),
        ).order_by(model.id).limit(MAX_CHECKPOINT_PEOPLE + 1)
            .with_for_update(read=True, nowait=True, of=model))).all()
        if len(admitted) > MAX_CHECKPOINT_PEOPLE:
            raise HistorySourceLimit()
        self.remaining_bytes -= sum(int(row.source_bytes) for row in admitted)
        if self.remaining_bytes < 0:
            raise HistorySourceLimit()
        ids = [row.id for row in admitted]
        if not ids:
            return []
        predicates = [model.agency_id == agency_id, model.group_id == group_id, model.id.in_(ids)]
        rows = (await self.session.execute(select(*columns).where(*predicates))).mappings().all()
        return [SimpleNamespace(**row) for row in rows]

    def _byte_size(self, columns: list[Any]) -> ColumnElement[int]:
        size: ColumnElement[int] = literal(0)
        postgres = self.session.get_bind().dialect.name == "postgresql"
        for column in columns:
            value = cast(column, Text)
            length = func.octet_length(value) if postgres else func.length(cast(value, LargeBinary))
            size = size + func.coalesce(length, 0)
        return size

    async def _admit(self, columns: list[Any], predicates: list[Any]) -> None:
        consumed = await self.session.scalar(select(func.coalesce(func.sum(self._byte_size(columns)), 0)).where(*predicates))
        self.remaining_bytes -= int(consumed or 0)
        if self.remaining_bytes < 0:
            raise HistorySourceLimit()

    async def history_count(self, predicates: list[Any]) -> int:
        return int(await self.session.scalar(select(func.count()).select_from(
            PassportExportHistoryModel).where(*predicates)) or 0)

    async def page_ids(self, predicates: list[Any], *, after: tuple[datetime, uuid.UUID] | None,
                       size: int) -> list[uuid.UUID]:
        model = PassportExportHistoryModel
        if after:
            predicates = [*predicates, or_(model.completed_at < after[0],
                and_(model.completed_at == after[0], model.id < after[1]))]
        return list((await self.session.scalars(select(model.id).where(*predicates)
            .order_by(model.completed_at.desc(), model.id.desc()).limit(size + 1))).all())

    async def checkpoints(self, identifiers: list[uuid.UUID], predicates: list[Any], *,
                          details: bool, personal: bool) -> list[Any]:
        if not identifiers:
            return []
        model = PassportExportHistoryModel
        scope = [*predicates, model.id.in_(identifiers)]
        locked = list((await self.session.scalars(select(model.id).where(*scope).order_by(model.id)
            .with_for_update(read=True, nowait=True))).all())
        columns: list[Any] = [model.id, model.export_kind, model.export_mode, model.baseline_export_id,
            model.total_available_count, model.exported_count, model.pending_recipient_count,
            model.created_at, model.completed_at]
        columns += ([model.exported_submission_ids, model.exported_people_snapshot] if details
                    else [model.snapshot_submission_ids,
                          model.artifact_metadata["submission_revisions"].label("submission_revisions")])
        if personal:
            columns.append(model.actor_email)
        await self._admit(columns, [*scope, model.id.in_(locked)])
        # Measure before materializing JSON, while SHARE locks keep admitted bytes stable.
        rows = (await self.session.execute(select(*columns).where(*scope, model.id.in_(locked))
            .order_by(model.completed_at.desc(), model.id.desc()))).mappings().all()
        return [SimpleNamespace(**row, artifact_metadata={"submission_revisions": row.get("submission_revisions") or {}}) for row in rows]

    async def available_ids(self, agency_id: uuid.UUID, group_id: uuid.UUID,
                            identifiers: list[uuid.UUID]) -> set[uuid.UUID]:
        if not identifiers:
            return set()
        return set((await self.session.scalars(select(PassportSubmissionModel.id).where(
            PassportSubmissionModel.id.in_(identifiers), PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.agency_id == agency_id))).all())
