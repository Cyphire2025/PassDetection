"""Pure closeout freshness, unresolved-work and aggregate readiness policy."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Sequence

from .attendance_closeout_types import (
    ATTENDANCE_CLOSEOUT_CHECKPOINT_TTL_SECONDS,
    AttendanceCloseoutAssignmentCheckpoint,
    AttendanceCloseoutCoordinatorStatus,
    AttendanceCloseoutCounts,
    AttendanceCloseoutStatus,
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _delivery_count(status: AttendanceCloseoutCoordinatorStatus) -> int:
    return status.pending_count + status.sending_count + status.retryable_count


def _unresolved_count(status: AttendanceCloseoutCoordinatorStatus) -> int:
    return _delivery_count(status) + status.needs_review_count + status.unreviewed_rejected_count


def _classify_checkpoint(
    assignment: AttendanceCloseoutAssignmentCheckpoint,
    *,
    activity_boundary: datetime,
    current: datetime,
    ttl_seconds: int,
) -> AttendanceCloseoutCoordinatorStatus:
    zero = AttendanceCloseoutCounts(0, 0, 0, 0, 0, None)
    counts = assignment.counts or zero
    reported_at = _utc(assignment.reported_at) if assignment.reported_at else None
    report_elapsed_seconds = (
        (current - reported_at).total_seconds() if reported_at is not None else None
    )
    report_age = max(0, int(report_elapsed_seconds)) if report_elapsed_seconds is not None else None
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
    return AttendanceCloseoutCoordinatorStatus(
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


def _summarize_checkpoints(
    coordinator_statuses: list[AttendanceCloseoutCoordinatorStatus], *, ttl_seconds: int
) -> AttendanceCloseoutStatus:
    unresolved_total = sum(_unresolved_count(item) for item in coordinator_statuses)
    oldest_ages = [
        item.oldest_pending_age_seconds
        for item in coordinator_statuses
        if _delivery_count(item) > 0 and item.oldest_pending_age_seconds is not None
    ]
    missing_count = sum(item.state == "missing" for item in coordinator_statuses)
    stale_count = sum(item.state == "stale" for item in coordinator_statuses)
    ready_count = sum(item.state == "ready" for item in coordinator_statuses)
    nonzero_count = sum(_unresolved_count(item) > 0 for item in coordinator_statuses)
    blocked_count = len(coordinator_statuses) - ready_count
    return AttendanceCloseoutStatus(
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


def classify_closeout_checkpoints(
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
    coordinator_statuses = [
        _classify_checkpoint(
            assignment,
            activity_boundary=activity_boundary,
            current=current,
            ttl_seconds=ttl_seconds,
        )
        for assignment in sorted(
            assignments,
            key=lambda item: (str(item.coordinator_id), str(item.runtime_id or "legacy")),
        )
    ]
    return _summarize_checkpoints(coordinator_statuses, ttl_seconds=ttl_seconds)
