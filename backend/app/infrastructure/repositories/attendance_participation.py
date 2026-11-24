"""Atomic event-time bounds shared by attendance scans and closeout checkpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import AttendanceSessionRuntimeParticipantModel


async def record_runtime_participation(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    session_id: uuid.UUID,
    coordinator_user_id: uuid.UUID,
    runtime_registration_id: uuid.UUID,
    source: Literal["scan", "checkpoint", "discard", "legacy"],
    occurred_at: datetime,
) -> None:
    """Retain both time bounds when saved events arrive out of order.

    Callers resolve runtime/tenant authority and own flushing/commit. SQL CASE
    reads the locked conflicting row, avoiding a separate read/update race.
    """
    model = AttendanceSessionRuntimeParticipantModel
    await session.execute(
        pg_insert(model)
        .values(
            id=uuid.uuid4(),
            agency_id=agency_id,
            session_id=session_id,
            coordinator_user_id=coordinator_user_id,
            runtime_registration_id=runtime_registration_id,
            participation_source=source,
            first_participated_at=occurred_at,
            last_participated_at=occurred_at,
        )
        .on_conflict_do_update(
            constraint="uq_attendance_session_runtime_participant",
            set_={
                "first_participated_at": case(
                    (model.first_participated_at > occurred_at, occurred_at),
                    else_=model.first_participated_at,
                ),
                "last_participated_at": case(
                    (model.last_participated_at < occurred_at, occurred_at),
                    else_=model.last_participated_at,
                ),
                "participation_source": source,
            },
        )
    )
