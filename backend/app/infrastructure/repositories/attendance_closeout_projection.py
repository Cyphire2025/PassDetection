"""Index stored evidence once and assemble each activity's closeout participants."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass

from .attendance_closeout_sources import (
    AssignmentSource,
    CheckpointSource,
    CloseoutSources,
    ParticipantSource,
    RuntimeSource,
)
from .attendance_closeout_types import (
    AttendanceCloseoutAssignmentCheckpoint,
    AttendanceCloseoutCounts,
)


@dataclass(frozen=True, slots=True)
class CloseoutSourceIndex:
    assignments: list[AssignmentSource]
    assignment_by_coordinator: dict[uuid.UUID, AssignmentSource]
    checkpoint_by_runtime: dict[tuple[uuid.UUID, uuid.UUID, uuid.UUID | None], CheckpointSource]
    runtime_by_id: dict[uuid.UUID, RuntimeSource]
    participants_by_activity: dict[uuid.UUID, list[ParticipantSource]]
    checkpoints_by_activity: dict[uuid.UUID, list[CheckpointSource]]


def index_closeout_sources(sources: CloseoutSources) -> CloseoutSourceIndex:
    participants: dict[uuid.UUID, list[ParticipantSource]] = defaultdict(list)
    checkpoints: dict[uuid.UUID, list[CheckpointSource]] = defaultdict(list)
    by_runtime: dict[tuple[uuid.UUID, uuid.UUID, uuid.UUID | None], CheckpointSource] = {}
    for participant in sources.participant_rows:
        participants[participant.session_id].append(participant)
    for checkpoint in sources.checkpoints:
        activity = checkpoint.session_id
        checkpoints[activity].append(checkpoint)
        by_runtime[
            (activity, checkpoint.coordinator_user_id, checkpoint.runtime_registration_id)
        ] = checkpoint
    return CloseoutSourceIndex(
        assignments=sources.assignment_rows,
        assignment_by_coordinator={row.coordinator_user_id: row for row in sources.assignment_rows},
        checkpoint_by_runtime=by_runtime,
        runtime_by_id={runtime.id: runtime for runtime in sources.runtimes},
        participants_by_activity=dict(participants),
        checkpoints_by_activity=dict(checkpoints),
    )


def _checkpoint_counts(checkpoint: CheckpointSource) -> AttendanceCloseoutCounts:
    return AttendanceCloseoutCounts(
        pending_count=checkpoint.pending_count,
        sending_count=checkpoint.sending_count,
        retryable_count=checkpoint.retryable_count,
        needs_review_count=checkpoint.needs_review_count,
        unreviewed_rejected_count=checkpoint.unreviewed_rejected_count,
        oldest_pending_age_seconds=checkpoint.oldest_pending_age_seconds,
    )


def _participant_assignment(
    index: CloseoutSourceIndex, session_id: uuid.UUID, participant: ParticipantSource
) -> AttendanceCloseoutAssignmentCheckpoint:
    coordinator_id = participant.coordinator_user_id
    runtime_id = participant.runtime_registration_id
    checkpoint = index.checkpoint_by_runtime.get((session_id, coordinator_id, runtime_id))
    group_assignment = index.assignment_by_coordinator.get(coordinator_id)
    assigned_at = participant.first_participated_at
    if group_assignment is not None:
        assigned_at = max(assigned_at, group_assignment.assigned_at)
    return AttendanceCloseoutAssignmentCheckpoint(
        coordinator_id=coordinator_id,
        coordinator_name=participant.full_name,
        assigned_at=assigned_at,
        reported_at=checkpoint.reported_at if checkpoint else None,
        counts=_checkpoint_counts(checkpoint) if checkpoint else None,
        runtime_id=runtime_id,
        runtime_kind=participant.runtime_kind,
        runtime_status=participant.runtime_status,
    )


def _rolling_assignment(
    index: CloseoutSourceIndex, checkpoint: CheckpointSource
) -> AttendanceCloseoutAssignmentCheckpoint | None:
    group_assignment = index.assignment_by_coordinator.get(checkpoint.coordinator_user_id)
    if group_assignment is None:
        return None
    runtime_kind = "legacy_account"
    runtime_status = "active"
    if checkpoint.runtime_registration_id is not None:
        runtime = index.runtime_by_id.get(checkpoint.runtime_registration_id)
        if runtime is None:
            runtime_status = "revoked"
        else:
            runtime_kind = runtime.runtime_kind
            runtime_status = runtime.status
    return AttendanceCloseoutAssignmentCheckpoint(
        coordinator_id=checkpoint.coordinator_user_id,
        coordinator_name=group_assignment.full_name,
        assigned_at=group_assignment.assigned_at,
        reported_at=checkpoint.reported_at,
        counts=_checkpoint_counts(checkpoint),
        runtime_id=checkpoint.runtime_registration_id,
        runtime_kind=runtime_kind,
        runtime_status=runtime_status,
    )


def activity_assignments(
    index: CloseoutSourceIndex, session_id: uuid.UUID
) -> list[AttendanceCloseoutAssignmentCheckpoint]:
    assignments: list[AttendanceCloseoutAssignmentCheckpoint] = []
    covered_coordinators: set[uuid.UUID] = set()
    covered_runtime_keys: set[tuple[uuid.UUID, uuid.UUID | None]] = set()
    for participant in index.participants_by_activity.get(session_id, []):
        assignments.append(_participant_assignment(index, session_id, participant))
        covered_coordinators.add(participant.coordinator_user_id)
        covered_runtime_keys.add(
            (participant.coordinator_user_id, participant.runtime_registration_id)
        )
    # Retain rolling-upgrade evidence that preceded runtime participation writes.
    for checkpoint in index.checkpoints_by_activity.get(session_id, []):
        runtime_key = (checkpoint.coordinator_user_id, checkpoint.runtime_registration_id)
        if runtime_key in covered_runtime_keys:
            continue
        assignment = _rolling_assignment(index, checkpoint)
        if assignment is None:
            continue
        assignments.append(assignment)
        covered_coordinators.add(checkpoint.coordinator_user_id)
        covered_runtime_keys.add(runtime_key)
    # Legacy clients remain account-scoped until a runtime participates.
    for row in index.assignments:
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
    return assignments
