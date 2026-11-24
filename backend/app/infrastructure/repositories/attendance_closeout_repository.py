"""Stable count-only closeout publication, bounded reads and classification seam."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.value_objects.attendance_read_limits import AttendanceReadLimits
from app.infrastructure.database.models import (
    AttendanceCloseoutCheckpointModel,
    AttendanceSessionModel,
)
from app.infrastructure.repositories.attendance_participation import record_runtime_participation

from .attendance_closeout_policy import _utc as _utc
from .attendance_closeout_policy import classify_closeout_checkpoints
from .attendance_closeout_projection import activity_assignments, index_closeout_sources
from .attendance_closeout_sources import load_closeout_sources
from .attendance_closeout_types import (
    ATTENDANCE_CLOSEOUT_CHECKPOINT_TTL_SECONDS as ATTENDANCE_CLOSEOUT_CHECKPOINT_TTL_SECONDS,
)
from .attendance_closeout_types import (
    AttendanceCloseoutAssignmentCheckpoint as AttendanceCloseoutAssignmentCheckpoint,
)
from .attendance_closeout_types import (
    AttendanceCloseoutCoordinatorStatus as AttendanceCloseoutCoordinatorStatus,
)
from .attendance_closeout_types import AttendanceCloseoutCounts as AttendanceCloseoutCounts
from .attendance_closeout_types import AttendanceCloseoutStatus as AttendanceCloseoutStatus


def classify_attendance_closeout(
    assignments: Sequence[AttendanceCloseoutAssignmentCheckpoint],
    *,
    activity_valid_after: datetime,
    now: datetime,
    ttl_seconds: int = ATTENDANCE_CLOSEOUT_CHECKPOINT_TTL_SECONDS,
) -> AttendanceCloseoutStatus:
    return classify_closeout_checkpoints(
        assignments, activity_valid_after=activity_valid_after, now=now, ttl_seconds=ttl_seconds
    )


class AttendanceCloseoutRepository:
    def __init__(
        self, session: AsyncSession, *, read_limits: AttendanceReadLimits | None = None
    ) -> None:
        self._session = session
        self._read_limits = read_limits

    async def publish(
        self,
        *,
        session_id: uuid.UUID,
        coordinator_user_id: uuid.UUID,
        counts: AttendanceCloseoutCounts,
        agency_id: uuid.UUID | None = None,
        runtime_registration_id: uuid.UUID | None = None,
        reported_at: datetime | None = None,
    ) -> AttendanceCloseoutCheckpointModel:
        if (
            min(
                counts.pending_count,
                counts.sending_count,
                counts.retryable_count,
                counts.needs_review_count,
                counts.unreviewed_rejected_count,
            )
            < 0
        ):
            raise ValueError("Attendance closeout counts cannot be negative")
        if (counts.delivery_count == 0) != (counts.oldest_pending_age_seconds is None):
            raise ValueError("Oldest pending age must match the delivery queue state")
        observed = _utc(reported_at or datetime.now(tz=UTC))
        if agency_id is None:
            agency_id = (
                await self._session.execute(
                    select(AttendanceSessionModel.agency_id).where(
                        AttendanceSessionModel.id == session_id
                    )
                )
            ).scalar_one()
        values = {
            "pending_count": counts.pending_count,
            "sending_count": counts.sending_count,
            "retryable_count": counts.retryable_count,
            "needs_review_count": counts.needs_review_count,
            "unreviewed_rejected_count": counts.unreviewed_rejected_count,
            "oldest_pending_age_seconds": counts.oldest_pending_age_seconds,
            "reported_at": observed,
        }
        insert_statement = pg_insert(AttendanceCloseoutCheckpointModel).values(
            id=uuid.uuid4(),
            agency_id=agency_id,
            session_id=session_id,
            coordinator_user_id=coordinator_user_id,
            runtime_registration_id=runtime_registration_id,
            **values,
        )
        if runtime_registration_id is None:
            statement = insert_statement.on_conflict_do_update(
                index_elements=(
                    AttendanceCloseoutCheckpointModel.session_id,
                    AttendanceCloseoutCheckpointModel.coordinator_user_id,
                ),
                index_where=AttendanceCloseoutCheckpointModel.runtime_registration_id.is_(None),
                set_=values,
            ).returning(AttendanceCloseoutCheckpointModel)
        else:
            statement = insert_statement.on_conflict_do_update(
                constraint="uq_attendance_closeout_checkpoint_runtime", set_=values
            ).returning(AttendanceCloseoutCheckpointModel)
        checkpoint = (await self._session.execute(statement)).scalar_one()
        if runtime_registration_id is not None:
            await record_runtime_participation(
                self._session,
                agency_id=agency_id,
                session_id=session_id,
                coordinator_user_id=coordinator_user_id,
                runtime_registration_id=runtime_registration_id,
                source="checkpoint",
                occurred_at=observed,
            )
        await self._session.flush()
        return checkpoint

    async def statuses(
        self,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        activity_valid_after: Mapping[uuid.UUID, datetime],
        now: datetime | None = None,
    ) -> dict[uuid.UUID, AttendanceCloseoutStatus]:
        if not activity_valid_after:
            return {}
        sources = await load_closeout_sources(
            self._session,
            agency_id=agency_id,
            group_id=group_id,
            activity_valid_after=activity_valid_after,
            read_limits=self._read_limits,
        )
        index = index_closeout_sources(sources)
        current = now or datetime.now(tz=UTC)
        return {
            session_id: classify_attendance_closeout(
                activity_assignments(index, session_id),
                activity_valid_after=valid_after,
                now=current,
            )
            for session_id, valid_after in activity_valid_after.items()
        }

    async def status(
        self,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        session_id: uuid.UUID,
        activity_valid_after: datetime,
        now: datetime | None = None,
    ) -> AttendanceCloseoutStatus:
        return (
            await self.statuses(
                agency_id=agency_id,
                group_id=group_id,
                activity_valid_after={session_id: activity_valid_after},
                now=now,
            )
        )[session_id]
