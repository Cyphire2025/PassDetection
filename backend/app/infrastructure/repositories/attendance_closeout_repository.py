"""Count-only attendance closeout persistence and coordinator classification."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    AttendanceCloseoutCheckpointModel,
    CoordinatorGroupAssignmentModel,
    UserModel,
)

ATTENDANCE_CLOSEOUT_CHECKPOINT_TTL_SECONDS = 120


@dataclass(frozen=True, slots=True)
class AttendanceCloseoutCounts:
    pending_count: int
    sending_count: int
    retryable_count: int
    needs_review_count: int
    unreviewed_rejected_count: int
    oldest_pending_age_seconds: int | None

    @property
    def delivery_count(self) -> int:
        return self.pending_count + self.sending_count + self.retryable_count

    @property
    def unresolved_count(self) -> int:
        return (
            self.delivery_count
            + self.needs_review_count
            + self.unreviewed_rejected_count
        )


@dataclass(frozen=True, slots=True)
class AttendanceCloseoutAssignmentCheckpoint:
    coordinator_id: uuid.UUID
    coordinator_name: str
    assigned_at: datetime
    reported_at: datetime | None
    counts: AttendanceCloseoutCounts | None


@dataclass(frozen=True, slots=True)
class AttendanceCloseoutCoordinatorStatus:
    coordinator_id: uuid.UUID
    coordinator_name: str
    state: Literal["ready", "missing", "stale", "blocked"]
    reported_at: datetime | None
    report_age_seconds: int | None
    pending_count: int
    sending_count: int
    retryable_count: int
    needs_review_count: int
    unreviewed_rejected_count: int
    oldest_pending_age_seconds: int | None


@dataclass(frozen=True, slots=True)
class AttendanceCloseoutStatus:
    ready: bool
    checkpoint_ttl_seconds: int
    active_assignment_count: int
    ready_assignment_count: int
    missing_assignment_count: int
    stale_assignment_count: int
    nonzero_assignment_count: int
    blocked_assignment_count: int
    unresolved_count: int
    oldest_pending_age_seconds: int | None
    coordinators: tuple[AttendanceCloseoutCoordinatorStatus, ...]


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def classify_attendance_closeout(
    assignments: Sequence[AttendanceCloseoutAssignmentCheckpoint],
    *,
    activity_valid_after: datetime,
    now: datetime,
    ttl_seconds: int = ATTENDANCE_CLOSEOUT_CHECKPOINT_TTL_SECONDS,
) -> AttendanceCloseoutStatus:
    """Classify every active assignment without trusting device identity."""

    if ttl_seconds <= 0:
        raise ValueError("Attendance closeout checkpoint TTL must be positive")
    current = _utc(now)
    activity_boundary = _utc(activity_valid_after)
    coordinator_statuses: list[AttendanceCloseoutCoordinatorStatus] = []
    unresolved_total = 0
    oldest_ages: list[int] = []

    for assignment in sorted(assignments, key=lambda item: str(item.coordinator_id)):
        zero = AttendanceCloseoutCounts(0, 0, 0, 0, 0, None)
        counts = assignment.counts or zero
        unresolved_total += counts.unresolved_count
        reported_at = _utc(assignment.reported_at) if assignment.reported_at else None
        report_elapsed_seconds = (
            (current - reported_at).total_seconds()
            if reported_at is not None
            else None
        )
        report_age = (
            max(0, int(report_elapsed_seconds))
            if report_elapsed_seconds is not None
            else None
        )
        valid_after = max(activity_boundary, _utc(assignment.assigned_at))
        stale = (
            reported_at is not None
            and (
                reported_at < valid_after
                or (report_elapsed_seconds or 0) > ttl_seconds
            )
        )
        if reported_at is None:
            state: Literal["ready", "missing", "stale", "blocked"] = "missing"
        elif stale:
            state = "stale"
        elif counts.unresolved_count > 0:
            state = "blocked"
        else:
            state = "ready"

        oldest_age = counts.oldest_pending_age_seconds
        if counts.delivery_count > 0 and oldest_age is not None:
            oldest_age = oldest_age + (report_age or 0)
            oldest_ages.append(oldest_age)
        coordinator_statuses.append(
            AttendanceCloseoutCoordinatorStatus(
                coordinator_id=assignment.coordinator_id,
                coordinator_name=assignment.coordinator_name,
                state=state,
                reported_at=reported_at,
                report_age_seconds=report_age,
                pending_count=counts.pending_count,
                sending_count=counts.sending_count,
                retryable_count=counts.retryable_count,
                needs_review_count=counts.needs_review_count,
                unreviewed_rejected_count=counts.unreviewed_rejected_count,
                oldest_pending_age_seconds=oldest_age,
            )
        )

    missing_count = sum(item.state == "missing" for item in coordinator_statuses)
    stale_count = sum(item.state == "stale" for item in coordinator_statuses)
    ready_count = sum(item.state == "ready" for item in coordinator_statuses)
    nonzero_count = sum(
        (
            item.pending_count
            + item.sending_count
            + item.retryable_count
            + item.needs_review_count
            + item.unreviewed_rejected_count
        )
        > 0
        for item in coordinator_statuses
    )
    blocked_count = len(coordinator_statuses) - ready_count
    return AttendanceCloseoutStatus(
        # An empty participant set is not affirmative closeout evidence. A
        # manager may still close through the explicit audited exception path.
        ready=bool(coordinator_statuses) and blocked_count == 0,
        checkpoint_ttl_seconds=ttl_seconds,
        active_assignment_count=len(coordinator_statuses),
        ready_assignment_count=ready_count,
        missing_assignment_count=missing_count,
        stale_assignment_count=stale_count,
        nonzero_assignment_count=nonzero_count,
        blocked_assignment_count=blocked_count,
        unresolved_count=unresolved_total,
        oldest_pending_age_seconds=max(oldest_ages) if oldest_ages else None,
        coordinators=tuple(coordinator_statuses),
    )


class AttendanceCloseoutRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def publish(
        self,
        *,
        session_id: uuid.UUID,
        coordinator_user_id: uuid.UUID,
        counts: AttendanceCloseoutCounts,
        reported_at: datetime | None = None,
    ) -> AttendanceCloseoutCheckpointModel:
        if min(
            counts.pending_count,
            counts.sending_count,
            counts.retryable_count,
            counts.needs_review_count,
            counts.unreviewed_rejected_count,
        ) < 0:
            raise ValueError("Attendance closeout counts cannot be negative")
        if (counts.delivery_count == 0) != (
            counts.oldest_pending_age_seconds is None
        ):
            raise ValueError("Oldest pending age must match the delivery queue state")
        observed = _utc(reported_at or datetime.now(tz=UTC))
        values = {
            "pending_count": counts.pending_count,
            "sending_count": counts.sending_count,
            "retryable_count": counts.retryable_count,
            "needs_review_count": counts.needs_review_count,
            "unreviewed_rejected_count": counts.unreviewed_rejected_count,
            "oldest_pending_age_seconds": counts.oldest_pending_age_seconds,
            "reported_at": observed,
        }
        statement = (
            pg_insert(AttendanceCloseoutCheckpointModel)
            .values(
                id=uuid.uuid4(),
                session_id=session_id,
                coordinator_user_id=coordinator_user_id,
                **values,
            )
            .on_conflict_do_update(
                constraint="uq_attendance_closeout_checkpoint_coordinator",
                set_=values,
            )
            .returning(AttendanceCloseoutCheckpointModel)
        )
        checkpoint = (await self._session.execute(statement)).scalar_one()
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
        assignment_rows = (
            await self._session.execute(
                select(
                    CoordinatorGroupAssignmentModel.coordinator_user_id,
                    UserModel.full_name,
                    CoordinatorGroupAssignmentModel.assigned_at,
                )
                .join(
                    UserModel,
                    UserModel.id
                    == CoordinatorGroupAssignmentModel.coordinator_user_id,
                )
                .where(
                    CoordinatorGroupAssignmentModel.agency_id == agency_id,
                    CoordinatorGroupAssignmentModel.group_id == group_id,
                    CoordinatorGroupAssignmentModel.active.is_(True),
                )
                .order_by(CoordinatorGroupAssignmentModel.coordinator_user_id)
            )
        ).all()
        coordinator_ids = [row.coordinator_user_id for row in assignment_rows]
        checkpoint_by_pair: dict[
            tuple[uuid.UUID, uuid.UUID],
            AttendanceCloseoutCheckpointModel,
        ] = {}
        if coordinator_ids:
            checkpoints = list(
                (
                    await self._session.execute(
                        select(AttendanceCloseoutCheckpointModel).where(
                            AttendanceCloseoutCheckpointModel.session_id.in_(
                                activity_valid_after
                            ),
                            AttendanceCloseoutCheckpointModel.coordinator_user_id.in_(
                                coordinator_ids
                            ),
                        )
                    )
                ).scalars()
            )
            checkpoint_by_pair = {
                (checkpoint.session_id, checkpoint.coordinator_user_id): checkpoint
                for checkpoint in checkpoints
            }

        current = now or datetime.now(tz=UTC)
        result: dict[uuid.UUID, AttendanceCloseoutStatus] = {}
        for session_id, valid_after in activity_valid_after.items():
            assignments: list[AttendanceCloseoutAssignmentCheckpoint] = []
            for row in assignment_rows:
                checkpoint = checkpoint_by_pair.get(
                    (session_id, row.coordinator_user_id)
                )
                assignments.append(
                    AttendanceCloseoutAssignmentCheckpoint(
                        coordinator_id=row.coordinator_user_id,
                        coordinator_name=row.full_name,
                        assigned_at=row.assigned_at,
                        reported_at=(checkpoint.reported_at if checkpoint else None),
                        counts=(
                            AttendanceCloseoutCounts(
                                pending_count=checkpoint.pending_count,
                                sending_count=checkpoint.sending_count,
                                retryable_count=checkpoint.retryable_count,
                                needs_review_count=checkpoint.needs_review_count,
                                unreviewed_rejected_count=(
                                    checkpoint.unreviewed_rejected_count
                                ),
                                oldest_pending_age_seconds=(
                                    checkpoint.oldest_pending_age_seconds
                                ),
                            )
                            if checkpoint
                            else None
                        ),
                    )
                )
            result[session_id] = classify_attendance_closeout(
                assignments,
                activity_valid_after=valid_after,
                now=current,
            )
        return result

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
