"""Append-only change journal used by compact incremental mobile sync."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.realtime_hints import stage_mobile_realtime_change
from app.infrastructure.database.gc_mobile_models import (
    GCGroupAccessModel,
    MobileSyncChangeModel,
)

SyncOperation = Literal["upsert", "delete", "revoke", "publish"]


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
