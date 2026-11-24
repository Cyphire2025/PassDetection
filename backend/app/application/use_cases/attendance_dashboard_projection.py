"""Count-only activity and coordinator response assembly."""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from app.application.attendance_closeout_read_contracts import (
    AttendanceCloseoutCoordinatorStatus,
    AttendanceCloseoutStatus,
)
from app.application.attendance_read_contracts import (
    AttendanceActivityAggregate,
    AttendanceGroupAggregate,
)
from app.application.use_cases.attendance_dashboard_revision import _activity_revision, _utc
from app.application.use_cases.attendance_dashboard_types import (
    AttendanceActivityDashboardSummary,
    AttendanceCloseoutAggregate,
    AttendanceCoordinatorDashboardSummary,
)


def _dashboard_activity(
    group: AttendanceGroupAggregate,
    activity: AttendanceActivityAggregate,
    closeout: AttendanceCloseoutStatus,
    *,
    visible_coordinator_ids: tuple[uuid.UUID, ...],
    coordinator_scan_counts: Mapping[tuple[uuid.UUID, uuid.UUID], int],
) -> AttendanceActivityDashboardSummary:
    exception_count = sum(
        item.needs_review_count + item.unreviewed_rejected_count for item in closeout.coordinators
    )
    closeout_aggregate = AttendanceCloseoutAggregate(
        ready=closeout.ready,
        active_participant_count=closeout.active_assignment_count,
        ready_participant_count=closeout.ready_assignment_count,
        blocked_participant_count=closeout.blocked_assignment_count,
        missing_participant_count=closeout.missing_assignment_count,
        stale_participant_count=closeout.stale_assignment_count,
        unresolved_count=closeout.unresolved_count,
    )
    last_update = max(
        _utc(value)
        for value in (
            activity.updated_at,
            group.roster.latest_updated_at,
            activity.latest_record_created_at,
        )
        if value is not None
    )
    coordinator_statuses: dict[uuid.UUID, list[AttendanceCloseoutCoordinatorStatus]] = {}
    for item in closeout.coordinators:
        coordinator_statuses.setdefault(item.coordinator_id, []).append(item)
    coordinators = tuple(
        _coordinator_summary(
            coordinator_statuses[coordinator_id],
            assigned_count=group.roster.passenger_count,
            scanned_count=coordinator_scan_counts.get(
                (activity.session_id, coordinator_id),
                0,
            ),
        )
        for coordinator_id in visible_coordinator_ids
        if coordinator_id in coordinator_statuses
    )
    return AttendanceActivityDashboardSummary(
        session_id=activity.session_id,
        name=activity.name,
        status=activity.status,
        revision=_activity_revision(group, activity),
        present_count=activity.present_count,
        missing_count=max(group.roster.passenger_count - activity.present_count, 0),
        exception_count=exception_count,
        closeout=closeout_aggregate,
        coordinator_count=len(coordinator_statuses),
        coordinators_truncated=len(coordinator_statuses) > len(coordinators),
        coordinators=coordinators,
        last_canonical_update_at=last_update,
        started_at=activity.started_at,
        completed_at=activity.completed_at,
    )


def _coordinator_summary(
    statuses: list[AttendanceCloseoutCoordinatorStatus],
    *,
    assigned_count: int,
    scanned_count: int,
) -> AttendanceCoordinatorDashboardSummary:
    state_priority = {"ready": 0, "stale": 1, "missing": 2, "blocked": 3}
    checkpoint_state = max(statuses, key=lambda item: state_priority[item.state]).state
    reported = tuple(_utc(item.reported_at) for item in statuses if item.reported_at is not None)
    # Closeout status advances queue age by the age of its checkpoint. Expose
    # the age observed at that checkpoint so an unchanged summary keeps a
    # truthful stable ETag instead of invalidating every repair poll.
    oldest_pending = tuple(
        max(
            0,
            item.oldest_pending_age_seconds - (item.report_age_seconds or 0),
        )
        for item in statuses
        if item.oldest_pending_age_seconds is not None
    )
    return AttendanceCoordinatorDashboardSummary(
        coordinator_id=statuses[0].coordinator_id,
        coordinator_name=min(item.coordinator_name for item in statuses),
        assigned_count=assigned_count,
        scanned_count=scanned_count,
        checkpoint_state=checkpoint_state,
        checkpoint_reported_at=max(reported) if reported else None,
        pending_count=sum(item.pending_count for item in statuses),
        sending_count=sum(item.sending_count for item in statuses),
        retryable_count=sum(item.retryable_count for item in statuses),
        needs_review_count=sum(item.needs_review_count for item in statuses),
        unreviewed_rejected_count=sum(item.unreviewed_rejected_count for item in statuses),
        oldest_pending_age_seconds=max(oldest_pending) if oldest_pending else None,
        runtime_count=len(statuses),
        active_runtime_count=sum(item.runtime_status == "active" for item in statuses),
    )
