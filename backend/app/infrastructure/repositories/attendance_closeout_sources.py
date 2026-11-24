"""Fixed tenant-scoped closeout queries and their bounded source projections."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.value_objects.attendance_read_limits import AttendanceReadLimits
from app.infrastructure.database.models import (
    AttendanceCloseoutCheckpointModel,
    AttendanceRuntimeRegistrationModel,
    AttendanceSessionRuntimeParticipantModel,
    CoordinatorGroupAssignmentModel,
    UserModel,
)
from app.infrastructure.repositories.attendance_projection_reads import (
    bounded_attendance_text,
    load_attendance_rows,
)


class AssignmentSource(Protocol):
    coordinator_user_id: uuid.UUID
    full_name: str
    assigned_at: datetime


class CheckpointSource(Protocol):
    session_id: uuid.UUID
    coordinator_user_id: uuid.UUID
    runtime_registration_id: uuid.UUID | None
    reported_at: datetime
    pending_count: int
    sending_count: int
    retryable_count: int
    needs_review_count: int
    unreviewed_rejected_count: int
    oldest_pending_age_seconds: int | None


class RuntimeSource(Protocol):
    id: uuid.UUID
    runtime_kind: str
    status: str


class ParticipantSource(Protocol):
    session_id: uuid.UUID
    coordinator_user_id: uuid.UUID
    runtime_registration_id: uuid.UUID
    first_participated_at: datetime
    runtime_kind: str
    runtime_status: str
    full_name: str


@dataclass(frozen=True, slots=True)
class CloseoutSources:
    assignment_rows: list[AssignmentSource]
    checkpoints: list[CheckpointSource]
    runtimes: list[RuntimeSource]
    participant_rows: list[ParticipantSource]


async def load_closeout_sources(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    activity_valid_after: Mapping[uuid.UUID, datetime],
    read_limits: AttendanceReadLimits | None,
) -> CloseoutSources:
    assignment_rows = await load_attendance_rows(
        session,
        select(
            CoordinatorGroupAssignmentModel.coordinator_user_id,
            bounded_attendance_text(UserModel.full_name, 255, read_limits),
            CoordinatorGroupAssignmentModel.assigned_at,
        )
        .join(UserModel, UserModel.id == CoordinatorGroupAssignmentModel.coordinator_user_id)
        .where(
            CoordinatorGroupAssignmentModel.agency_id == agency_id,
            CoordinatorGroupAssignmentModel.group_id == group_id,
            CoordinatorGroupAssignmentModel.active.is_(True),
        )
        .order_by(CoordinatorGroupAssignmentModel.coordinator_user_id),
        limits=read_limits,
        text_limits=(("full_name", 255),),
    )
    checkpoint_model = AttendanceCloseoutCheckpointModel
    checkpoints = await load_attendance_rows(
        session,
        select(checkpoint_model).where(
            checkpoint_model.agency_id == agency_id,
            checkpoint_model.session_id.in_(activity_valid_after),
        ),
        limits=read_limits,
        scalar=True,
        projection=(
            checkpoint_model.session_id,
            checkpoint_model.coordinator_user_id,
            checkpoint_model.runtime_registration_id,
            checkpoint_model.reported_at,
            checkpoint_model.pending_count,
            checkpoint_model.sending_count,
            checkpoint_model.retryable_count,
            checkpoint_model.needs_review_count,
            checkpoint_model.unreviewed_rejected_count,
            checkpoint_model.oldest_pending_age_seconds,
        ),
    )
    runtime_ids = {
        checkpoint.runtime_registration_id
        for checkpoint in checkpoints
        if checkpoint.runtime_registration_id is not None
    }
    runtime_model = AttendanceRuntimeRegistrationModel
    runtimes = (
        await load_attendance_rows(
            session,
            select(runtime_model).where(
                runtime_model.id.in_(runtime_ids), runtime_model.agency_id == agency_id
            ),
            limits=read_limits,
            scalar=True,
            projection=(runtime_model.id, runtime_model.runtime_kind, runtime_model.status),
        )
        if runtime_ids
        else []
    )
    participant_rows = await load_attendance_rows(
        session,
        select(
            AttendanceSessionRuntimeParticipantModel.session_id,
            AttendanceSessionRuntimeParticipantModel.coordinator_user_id,
            AttendanceSessionRuntimeParticipantModel.first_participated_at,
            AttendanceSessionRuntimeParticipantModel.runtime_registration_id,
            AttendanceRuntimeRegistrationModel.runtime_kind,
            AttendanceRuntimeRegistrationModel.status.label("runtime_status"),
            bounded_attendance_text(UserModel.full_name, 255, read_limits),
        )
        .join(
            AttendanceRuntimeRegistrationModel,
            AttendanceRuntimeRegistrationModel.id
            == AttendanceSessionRuntimeParticipantModel.runtime_registration_id,
        )
        .join(
            UserModel, UserModel.id == AttendanceSessionRuntimeParticipantModel.coordinator_user_id
        )
        .where(
            AttendanceSessionRuntimeParticipantModel.agency_id == agency_id,
            AttendanceSessionRuntimeParticipantModel.session_id.in_(activity_valid_after),
        ),
        limits=read_limits,
        text_limits=(("full_name", 255),),
    )
    if read_limits:
        read_limits.require_work(
            len(activity_valid_after),
            len(assignment_rows) + len(checkpoints) + len(participant_rows),
        )
    return CloseoutSources(assignment_rows, checkpoints, runtimes, participant_rows)
