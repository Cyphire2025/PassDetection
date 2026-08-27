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
    AttendanceRuntimeRegistrationModel,
    AttendanceSessionModel,
    AttendanceSessionRuntimeParticipantModel,
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
        return self.delivery_count + self.needs_review_count + self.unreviewed_rejected_count


@dataclass(frozen=True, slots=True)
class AttendanceCloseoutAssignmentCheckpoint:
    coordinator_id: uuid.UUID
    coordinator_name: str
    assigned_at: datetime
    reported_at: datetime | None
    counts: AttendanceCloseoutCounts | None
    runtime_id: uuid.UUID | None = None
    runtime_kind: str = "legacy_account"
    runtime_status: str = "active"


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
    runtime_id: uuid.UUID | None
    runtime_kind: str
    runtime_status: str


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

    for assignment in sorted(
        assignments,
        key=lambda item: (str(item.coordinator_id), str(item.runtime_id or "legacy")),
    ):
        zero = AttendanceCloseoutCounts(0, 0, 0, 0, 0, None)
        counts = assignment.counts or zero
        unresolved_total += counts.unresolved_count
        reported_at = _utc(assignment.reported_at) if assignment.reported_at else None
        report_elapsed_seconds = (
            (current - reported_at).total_seconds() if reported_at is not None else None
        )
        report_age = (
            max(0, int(report_elapsed_seconds)) if report_elapsed_seconds is not None else None
        )
        valid_after = max(activity_boundary, _utc(assignment.assigned_at))
        stale = reported_at is not None and (
            reported_at < valid_after or (report_elapsed_seconds or 0) > ttl_seconds
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
                runtime_id=assignment.runtime_id,
                runtime_kind=assignment.runtime_kind,
                runtime_status=assignment.runtime_status,
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
                index_where=(AttendanceCloseoutCheckpointModel.runtime_registration_id.is_(None)),
                set_=values,
            ).returning(AttendanceCloseoutCheckpointModel)
        else:
            statement = insert_statement.on_conflict_do_update(
                constraint="uq_attendance_closeout_checkpoint_runtime",
                set_=values,
            ).returning(AttendanceCloseoutCheckpointModel)
        checkpoint = (await self._session.execute(statement)).scalar_one()
        if runtime_registration_id is not None:
            participant_values = {
                "last_participated_at": observed,
                "participation_source": "checkpoint",
            }
            await self._session.execute(
                pg_insert(AttendanceSessionRuntimeParticipantModel)
                .values(
                    id=uuid.uuid4(),
                    agency_id=agency_id,
                    session_id=session_id,
                    coordinator_user_id=coordinator_user_id,
                    runtime_registration_id=runtime_registration_id,
                    participation_source="checkpoint",
                    first_participated_at=observed,
                    last_participated_at=observed,
                )
                .on_conflict_do_update(
                    constraint="uq_attendance_session_runtime_participant",
                    set_=participant_values,
                )
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
        assignment_rows = (
            await self._session.execute(
                select(
                    CoordinatorGroupAssignmentModel.coordinator_user_id,
                    UserModel.full_name,
                    CoordinatorGroupAssignmentModel.assigned_at,
                )
                .join(
                    UserModel,
                    UserModel.id == CoordinatorGroupAssignmentModel.coordinator_user_id,
                )
                .where(
                    CoordinatorGroupAssignmentModel.agency_id == agency_id,
                    CoordinatorGroupAssignmentModel.group_id == group_id,
                    CoordinatorGroupAssignmentModel.active.is_(True),
                )
                .order_by(CoordinatorGroupAssignmentModel.coordinator_user_id)
            )
        ).all()
        assignment_by_coordinator = {row.coordinator_user_id: row for row in assignment_rows}
        checkpoints = list(
            (
                await self._session.execute(
                    select(AttendanceCloseoutCheckpointModel).where(
                        AttendanceCloseoutCheckpointModel.agency_id == agency_id,
                        AttendanceCloseoutCheckpointModel.session_id.in_(activity_valid_after),
                    )
                )
            ).scalars()
        )
        checkpoint_by_runtime = {
            (
                checkpoint.session_id,
                checkpoint.coordinator_user_id,
                checkpoint.runtime_registration_id,
            ): checkpoint
            for checkpoint in checkpoints
        }
        runtime_ids = {
            checkpoint.runtime_registration_id
            for checkpoint in checkpoints
            if checkpoint.runtime_registration_id is not None
        }
        runtimes = (
            list(
                (
                    await self._session.execute(
                        select(AttendanceRuntimeRegistrationModel).where(
                            AttendanceRuntimeRegistrationModel.id.in_(runtime_ids),
                            AttendanceRuntimeRegistrationModel.agency_id == agency_id,
                        )
                    )
                ).scalars()
            )
            if runtime_ids
            else []
        )
        runtime_by_id = {runtime.id: runtime for runtime in runtimes}
        participant_rows = (
            await self._session.execute(
                select(
                    AttendanceSessionRuntimeParticipantModel.session_id,
                    AttendanceSessionRuntimeParticipantModel.coordinator_user_id,
                    AttendanceSessionRuntimeParticipantModel.first_participated_at,
                    AttendanceSessionRuntimeParticipantModel.runtime_registration_id,
                    AttendanceRuntimeRegistrationModel.runtime_kind,
                    AttendanceRuntimeRegistrationModel.status.label("runtime_status"),
                    UserModel.full_name,
                )
                .join(
                    AttendanceRuntimeRegistrationModel,
                    AttendanceRuntimeRegistrationModel.id
                    == AttendanceSessionRuntimeParticipantModel.runtime_registration_id,
                )
                .join(
                    UserModel,
                    UserModel.id == AttendanceSessionRuntimeParticipantModel.coordinator_user_id,
                )
                .where(
                    AttendanceSessionRuntimeParticipantModel.agency_id == agency_id,
                    AttendanceSessionRuntimeParticipantModel.session_id.in_(activity_valid_after),
                )
            )
        ).all()

        current = now or datetime.now(tz=UTC)
        result: dict[uuid.UUID, AttendanceCloseoutStatus] = {}
        for session_id, valid_after in activity_valid_after.items():
            assignments: list[AttendanceCloseoutAssignmentCheckpoint] = []
            covered_coordinators: set[uuid.UUID] = set()
            covered_runtime_keys: set[tuple[uuid.UUID, uuid.UUID | None]] = set()
            for participant in participant_rows:
                if participant.session_id != session_id:
                    continue
                coordinator_id = participant.coordinator_user_id
                runtime_id = participant.runtime_registration_id
                checkpoint = checkpoint_by_runtime.get((session_id, coordinator_id, runtime_id))
                group_assignment = assignment_by_coordinator.get(coordinator_id)
                assigned_at = participant.first_participated_at
                if group_assignment is not None:
                    assigned_at = max(assigned_at, group_assignment.assigned_at)
                assignments.append(
                    AttendanceCloseoutAssignmentCheckpoint(
                        coordinator_id=coordinator_id,
                        coordinator_name=participant.full_name,
                        assigned_at=assigned_at,
                        reported_at=(checkpoint.reported_at if checkpoint else None),
                        counts=(
                            AttendanceCloseoutCounts(
                                pending_count=checkpoint.pending_count,
                                sending_count=checkpoint.sending_count,
                                retryable_count=checkpoint.retryable_count,
                                needs_review_count=checkpoint.needs_review_count,
                                unreviewed_rejected_count=(checkpoint.unreviewed_rejected_count),
                                oldest_pending_age_seconds=(checkpoint.oldest_pending_age_seconds),
                            )
                            if checkpoint
                            else None
                        ),
                        runtime_id=runtime_id,
                        runtime_kind=participant.runtime_kind,
                        runtime_status=participant.runtime_status,
                    )
                )
                covered_coordinators.add(coordinator_id)
                covered_runtime_keys.add((coordinator_id, runtime_id))

            # Preserve rolling-upgrade evidence even if a new runtime client
            # published before the participation upsert reached production.
            for checkpoint in checkpoints:
                if checkpoint.session_id != session_id:
                    continue
                runtime_key = (
                    checkpoint.coordinator_user_id,
                    checkpoint.runtime_registration_id,
                )
                if runtime_key in covered_runtime_keys:
                    continue
                group_assignment = assignment_by_coordinator.get(checkpoint.coordinator_user_id)
                if group_assignment is None:
                    continue
                runtime_kind = "legacy_account"
                runtime_status = "active"
                if checkpoint.runtime_registration_id is not None:
                    runtime = runtime_by_id.get(checkpoint.runtime_registration_id)
                    if runtime is None:
                        runtime_status = "revoked"
                    else:
                        runtime_kind = runtime.runtime_kind
                        runtime_status = runtime.status
                assignments.append(
                    AttendanceCloseoutAssignmentCheckpoint(
                        coordinator_id=checkpoint.coordinator_user_id,
                        coordinator_name=group_assignment.full_name,
                        assigned_at=group_assignment.assigned_at,
                        reported_at=checkpoint.reported_at,
                        counts=AttendanceCloseoutCounts(
                            pending_count=checkpoint.pending_count,
                            sending_count=checkpoint.sending_count,
                            retryable_count=checkpoint.retryable_count,
                            needs_review_count=checkpoint.needs_review_count,
                            unreviewed_rejected_count=(checkpoint.unreviewed_rejected_count),
                            oldest_pending_age_seconds=(checkpoint.oldest_pending_age_seconds),
                        ),
                        runtime_id=checkpoint.runtime_registration_id,
                        runtime_kind=runtime_kind,
                        runtime_status=runtime_status,
                    )
                )
                covered_coordinators.add(checkpoint.coordinator_user_id)
                covered_runtime_keys.add(runtime_key)

            # Old clients have no runtime identity. They retain the legacy
            # account-scoped behavior until at least one runtime participates.
            for row in assignment_rows:
                if row.coordinator_user_id in covered_coordinators:
                    continue
                assignments.append(
                    AttendanceCloseoutAssignmentCheckpoint(
                        coordinator_id=row.coordinator_user_id,
                        coordinator_name=row.full_name,
                        assigned_at=row.assigned_at,
                        reported_at=None,
                        counts=None,
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
