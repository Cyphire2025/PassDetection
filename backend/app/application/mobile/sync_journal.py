"""Append-only change journal used by compact incremental mobile sync."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.realtime_hints import stage_mobile_realtime_change
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobileSyncChangeModel,
)

SyncOperation = Literal["upsert", "delete", "revoke", "publish"]
AttendanceRealtimeEntityType = Literal[
    "attendance_record",
    "attendance_session",
    "attendance_checkpoint",
]


async def append_attendance_realtime_change(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    attendance_record_id: uuid.UUID,
    coordinator_user_id: uuid.UUID,
    occurred_at: datetime,
) -> MobileSyncChangeModel:
    """Journal one canonical scan without enabling any mobile audience."""

    return await append_attendance_realtime_invalidation(
        session,
        agency_id=agency_id,
        group_id=group_id,
        change_id=attendance_record_id,
        entity_type="attendance_record",
        entity_id=attendance_record_id,
        changed_by_user_id=coordinator_user_id,
        occurred_at=occurred_at,
    )


async def append_attendance_realtime_invalidation(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    entity_type: AttendanceRealtimeEntityType,
    entity_id: uuid.UUID,
    changed_by_user_id: uuid.UUID,
    occurred_at: datetime,
    change_id: uuid.UUID | None = None,
) -> MobileSyncChangeModel:
    """Journal attendance state without enabling any mobile audience.

    Some dashboard-managed groups have never been configured for GC App. A
    disabled access row is therefore created as an inert journal anchor. It
    grants no mobile access, but lets dashboard and mobile attendance writes
    share the existing durable cursor and post-commit realtime pipeline.
    """

    anchor_id = uuid.uuid4()
    await session.execute(
        pg_insert(GCGroupAccessModel)
        .values(
            id=anchor_id,
            agency_id=agency_id,
            group_id=group_id,
            client_organization_id=None,
            is_enabled=False,
            passenger_access_enabled=False,
            client_manager_access_enabled=False,
            coordinator_access_enabled=False,
            access_generation=0,
            revision=1,
            manifest_version=0,
            itinerary_version=0,
            common_document_version=0,
            announcement_version=0,
            rooming_version=0,
            meal_version=0,
            qr_version=0,
            created_by_user_id=changed_by_user_id,
            updated_by_user_id=changed_by_user_id,
            created_at=occurred_at,
            updated_at=occurred_at,
        )
        .on_conflict_do_nothing(index_elements=[GCGroupAccessModel.group_id])
    )
    access = (
        await session.execute(
            select(GCGroupAccessModel).where(
                GCGroupAccessModel.agency_id == agency_id,
                GCGroupAccessModel.group_id == group_id,
            )
        )
    ).scalar_one()
    return await append_mobile_sync_change(
        session,
        access=access,
        change_id=change_id,
        audience="coordinator",
        entity_type=entity_type,
        entity_id=entity_id,
        operation="upsert",
        version=max(1, int(occurred_at.timestamp() * 1_000)),
        changed_by_user_id=changed_by_user_id,
        payload={},
    )


async def append_mobile_sync_change(
    session: AsyncSession,
    *,
    access: GCGroupAccessModel,
    change_id: uuid.UUID | None = None,
    entity_type: str,
    entity_id: uuid.UUID | None,
    operation: SyncOperation,
    version: int,
    changed_by_user_id: uuid.UUID | None,
    audience: Literal["all", "passenger", "client_manager", "coordinator"] = "all",
    passenger_identity_id: uuid.UUID | None = None,
    payload: dict[str, object] | None = None,
    flush: bool = True,
) -> MobileSyncChangeModel:
    """Append a tenant/group-bound change in the caller's DB transaction.

    ``flush=False`` is reserved for callers that build a bounded batch and
    explicitly flush it before returning. The default preserves the existing
    immediate-write behavior for every other workflow.
    """

    change = MobileSyncChangeModel(
        id=change_id or uuid.uuid4(),
        agency_id=access.agency_id,
        group_id=access.group_id,
        gc_group_access_id=access.id,
        passenger_identity_id=passenger_identity_id,
        audience=audience,
        entity_type=entity_type,
        entity_id=entity_id,
        operation=operation,
        version=version,
        access_generation=access.access_generation,
        payload=payload or {},
        changed_by_user_id=changed_by_user_id,
        occurred_at=datetime.now(tz=UTC),
    )
    session.add(change)
    stage_mobile_realtime_change(session, change)
    if flush:
        await session.flush()
    return change


__all__ = [
    "AttendanceRealtimeEntityType",
    "SyncOperation",
    "append_attendance_realtime_change",
    "append_attendance_realtime_invalidation",
    "append_mobile_sync_change",
]
