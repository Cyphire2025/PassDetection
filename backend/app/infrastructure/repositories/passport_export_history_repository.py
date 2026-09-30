"""Persistence helpers for immutable passport export checkpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.value_objects.passport_export_history import (
    PassportExportKind as PassportExportKind,
)
from app.domain.value_objects.passport_export_history import (
    PassportExportMode as PassportExportMode,
)
from app.domain.value_objects.passport_export_history import (
    PassportExportPersonSnapshot as PassportExportPersonSnapshot,
)
from app.domain.value_objects.passport_export_history import (
    validated_export_people_snapshot as validated_export_people_snapshot,
)
from app.infrastructure.database.models import PassportExportHistoryModel


class PassportExportHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_group(
        self,
        *,
        group_id: uuid.UUID,
        agency_id: uuid.UUID,
        export_kind: PassportExportKind,
        created_by_user_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[PassportExportHistoryModel]:
        stmt = select(PassportExportHistoryModel).where(
            PassportExportHistoryModel.group_id == group_id,
            PassportExportHistoryModel.agency_id == agency_id,
            PassportExportHistoryModel.export_kind == export_kind,
            PassportExportHistoryModel.format_version == 1,
            PassportExportHistoryModel.status == "completed",
        )
        if created_by_user_id is not None:
            stmt = stmt.where(PassportExportHistoryModel.created_by_user_id == created_by_user_id)
        result = await self._session.execute(
            stmt.order_by(
                PassportExportHistoryModel.completed_at.desc(),
                PassportExportHistoryModel.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_for_group(
        self,
        *,
        group_id: uuid.UUID,
        agency_id: uuid.UUID,
        export_kind: PassportExportKind,
        created_by_user_id: uuid.UUID | None = None,
    ) -> int:
        stmt = (
            select(func.count())
            .select_from(PassportExportHistoryModel)
            .where(
                PassportExportHistoryModel.group_id == group_id,
                PassportExportHistoryModel.agency_id == agency_id,
                PassportExportHistoryModel.export_kind == export_kind,
                PassportExportHistoryModel.format_version == 1,
                PassportExportHistoryModel.status == "completed",
            )
        )
        if created_by_user_id is not None:
            stmt = stmt.where(
                PassportExportHistoryModel.created_by_user_id
                == created_by_user_id
            )
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def get_compatible_baseline(
        self,
        *,
        history_id: uuid.UUID,
        group_id: uuid.UUID,
        agency_id: uuid.UUID,
        export_kind: PassportExportKind,
        created_by_user_id: uuid.UUID | None = None,
    ) -> PassportExportHistoryModel | None:
        stmt = select(PassportExportHistoryModel).where(
            PassportExportHistoryModel.id == history_id,
            PassportExportHistoryModel.group_id == group_id,
            PassportExportHistoryModel.agency_id == agency_id,
            PassportExportHistoryModel.export_kind == export_kind,
            PassportExportHistoryModel.format_version == 1,
            PassportExportHistoryModel.status == "completed",
        )
        if created_by_user_id is not None:
            stmt = stmt.where(PassportExportHistoryModel.created_by_user_id == created_by_user_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_group(
        self,
        *,
        history_id: uuid.UUID,
        group_id: uuid.UUID,
        agency_id: uuid.UUID,
        created_by_user_id: uuid.UUID | None = None,
    ) -> PassportExportHistoryModel | None:
        stmt = select(PassportExportHistoryModel).where(
            PassportExportHistoryModel.id == history_id,
            PassportExportHistoryModel.group_id == group_id,
            PassportExportHistoryModel.agency_id == agency_id,
            PassportExportHistoryModel.format_version == 1,
            PassportExportHistoryModel.status == "completed",
        )
        if created_by_user_id is not None:
            stmt = stmt.where(PassportExportHistoryModel.created_by_user_id == created_by_user_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_for_completion(
        self,
        *,
        history_id: uuid.UUID,
        group_id: uuid.UUID,
        agency_id: uuid.UUID,
        created_by_user_id: uuid.UUID,
    ) -> PassportExportHistoryModel | None:
        result = await self._session.execute(
            select(PassportExportHistoryModel)
            .where(
                PassportExportHistoryModel.id == history_id,
                PassportExportHistoryModel.group_id == group_id,
                PassportExportHistoryModel.agency_id == agency_id,
                PassportExportHistoryModel.created_by_user_id
                == created_by_user_id,
                PassportExportHistoryModel.format_version == 1,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none()

    async def get_by_request(
        self,
        *,
        group_id: uuid.UUID,
        agency_id: uuid.UUID,
        export_kind: PassportExportKind,
        request_id: uuid.UUID,
        created_by_user_id: uuid.UUID | None = None,
    ) -> PassportExportHistoryModel | None:
        stmt = select(PassportExportHistoryModel).where(
            PassportExportHistoryModel.group_id == group_id,
            PassportExportHistoryModel.agency_id == agency_id,
            PassportExportHistoryModel.export_kind == export_kind,
            PassportExportHistoryModel.request_id == request_id,
        )
        if created_by_user_id is not None:
            stmt = stmt.where(PassportExportHistoryModel.created_by_user_id == created_by_user_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def record(
        self,
        *,
        group_id: uuid.UUID,
        agency_id: uuid.UUID,
        export_kind: PassportExportKind,
        export_mode: PassportExportMode,
        request_id: uuid.UUID,
        snapshot_submission_ids: list[uuid.UUID],
        exported_submission_ids: list[uuid.UUID],
        exported_people_snapshot: list[PassportExportPersonSnapshot],
        created_by_user_id: uuid.UUID | None,
        actor_email: str | None,
        baseline_export_id: uuid.UUID | None = None,
        pending_recipient_count: int = 0,
        artifact_metadata: dict[str, object] | None = None,
    ) -> PassportExportHistoryModel:
        if len(set(snapshot_submission_ids)) != len(snapshot_submission_ids):
            raise ValueError("Export checkpoint submission IDs must be unique.")
        if len(set(exported_submission_ids)) != len(exported_submission_ids):
            raise ValueError("Export payload submission IDs must be unique.")
        if not set(exported_submission_ids).issubset(snapshot_submission_ids):
            raise ValueError("Every exported submission must belong to the cumulative checkpoint.")
        canonical_people_snapshot = validated_export_people_snapshot(
            exported_people_snapshot,
            exported_submission_ids=exported_submission_ids,
        )
        model = PassportExportHistoryModel(
            id=uuid.uuid4(),
            group_id=group_id,
            agency_id=agency_id,
            export_kind=export_kind,
            export_mode=export_mode,
            request_id=request_id,
            format_version=1,
            baseline_export_id=baseline_export_id,
            snapshot_submission_ids=[
                str(submission_id) for submission_id in snapshot_submission_ids
            ],
            exported_submission_ids=[
                str(submission_id) for submission_id in exported_submission_ids
            ],
            exported_people_snapshot=canonical_people_snapshot,
            total_available_count=len(snapshot_submission_ids),
            exported_count=len(exported_submission_ids),
            pending_recipient_count=pending_recipient_count,
            artifact_metadata=artifact_metadata or {},
            created_by_user_id=created_by_user_id,
            actor_email=actor_email,
            status="prepared",
            created_at=datetime.now(tz=UTC),
            completed_at=None,
        )
        self._session.add(model)
        await self._session.flush()
        return model
