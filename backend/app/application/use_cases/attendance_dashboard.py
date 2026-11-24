"""Office-attendance query orchestration and public compatibility surface."""

from __future__ import annotations

import uuid
from collections.abc import Mapping

from app.application.use_cases.attendance_dashboard_projection import (
    _coordinator_summary as _coordinator_summary,
)
from app.application.use_cases.attendance_dashboard_projection import _dashboard_activity
from app.application.use_cases.attendance_dashboard_revision import (
    _activity_revision,
    _find_activity,
    _opaque_revision,
)
from app.application.use_cases.attendance_dashboard_revision import _revision_part as _revision_part
from app.application.use_cases.attendance_dashboard_revision import _utc as _utc
from app.application.use_cases.attendance_dashboard_types import (
    AttendanceActivityDashboardSummary as AttendanceActivityDashboardSummary,
)
from app.application.use_cases.attendance_dashboard_types import (
    AttendanceActivityNotFoundError as AttendanceActivityNotFoundError,
)
from app.application.use_cases.attendance_dashboard_types import (
    AttendanceCloseoutAggregate as AttendanceCloseoutAggregate,
)
from app.application.use_cases.attendance_dashboard_types import (
    AttendanceCoordinatorDashboardSummary as AttendanceCoordinatorDashboardSummary,
)
from app.application.use_cases.attendance_dashboard_types import (
    AttendanceGroupDashboardSummary as AttendanceGroupDashboardSummary,
)
from app.application.use_cases.attendance_dashboard_types import (
    AttendanceMissingDashboardPage as AttendanceMissingDashboardPage,
)
from app.application.use_cases.attendance_dashboard_types import (
    AttendanceSnapshotChangedError as AttendanceSnapshotChangedError,
)
from app.infrastructure.repositories.attendance_closeout_repository import (
    AttendanceCloseoutCoordinatorStatus as AttendanceCloseoutCoordinatorStatus,
)
from app.infrastructure.repositories.attendance_closeout_repository import (
    AttendanceCloseoutRepository,
    AttendanceCloseoutStatus,
)
from app.infrastructure.repositories.attendance_dashboard_repository import (
    MAX_ATTENDANCE_SUMMARY_COORDINATORS,
    AttendanceCoordinatorScanAggregate,
    AttendanceDashboardRepository,
)
from app.infrastructure.repositories.attendance_dashboard_repository import (
    AttendanceActivityAggregate as AttendanceActivityAggregate,
)
from app.infrastructure.repositories.attendance_dashboard_repository import (
    AttendanceGroupAggregate as AttendanceGroupAggregate,
)
from app.infrastructure.repositories.attendance_dashboard_repository import (
    MissingPassengerPage as MissingPassengerPage,
)


class AttendanceDashboardService:
    def __init__(
        self,
        repository: AttendanceDashboardRepository,
        closeout_repository: AttendanceCloseoutRepository,
    ) -> None:
        self._repository = repository
        self._closeout_repository = closeout_repository

    async def summary(
        self,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        group_name: str,
    ) -> AttendanceGroupDashboardSummary:
        aggregate = await self._repository.group_aggregate(
            agency_id=agency_id,
            group_id=group_id,
        )
        closeout_statuses: dict[uuid.UUID, AttendanceCloseoutStatus]
        if aggregate.activities:
            closeout_statuses = await self._closeout_repository.statuses(
                agency_id=agency_id,
                group_id=group_id,
                activity_valid_after={
                    activity.session_id: activity.started_at or activity.created_at
                    for activity in aggregate.activities
                },
            )
        else:
            closeout_statuses = {}

        visible_coordinator_ids = _visible_coordinator_ids(closeout_statuses)
        coordinator_scan_rows: tuple[AttendanceCoordinatorScanAggregate, ...]
        if aggregate.activities and visible_coordinator_ids:
            coordinator_scan_rows = await self._repository.coordinator_scan_counts(
                agency_id=agency_id,
                group_id=group_id,
                session_ids=tuple(activity.session_id for activity in aggregate.activities),
                coordinator_ids=visible_coordinator_ids,
            )
        else:
            coordinator_scan_rows = ()
        coordinator_scan_counts = {
            (row.session_id, row.coordinator_id): row.scanned_count for row in coordinator_scan_rows
        }

        activities = tuple(
            _dashboard_activity(
                aggregate,
                activity,
                closeout_statuses[activity.session_id],
                visible_coordinator_ids=visible_coordinator_ids,
                coordinator_scan_counts=coordinator_scan_counts,
            )
            for activity in aggregate.activities
        )
        coordinator_revision_parts = tuple(
            value
            for activity in activities
            for coordinator in activity.coordinators
            for value in (
                coordinator.coordinator_id,
                coordinator.coordinator_name,
                coordinator.assigned_count,
                coordinator.scanned_count,
                coordinator.checkpoint_state,
                coordinator.checkpoint_reported_at,
                coordinator.pending_count,
                coordinator.sending_count,
                coordinator.retryable_count,
                coordinator.needs_review_count,
                coordinator.unreviewed_rejected_count,
                coordinator.oldest_pending_age_seconds,
                coordinator.runtime_count,
                coordinator.active_runtime_count,
            )
        )
        revision = _opaque_revision(
            group_id,
            group_name,
            aggregate.roster.passenger_count,
            aggregate.roster.latest_updated_at,
            aggregate.roster.latest_passenger_key,
            *(
                value
                for activity in activities
                for value in (
                    activity.revision,
                    activity.status,
                    activity.exception_count,
                    activity.closeout.ready,
                    activity.closeout.active_participant_count,
                    activity.closeout.ready_participant_count,
                    activity.closeout.blocked_participant_count,
                    activity.closeout.missing_participant_count,
                    activity.closeout.stale_participant_count,
                    activity.closeout.unresolved_count,
                    activity.coordinator_count,
                    activity.coordinators_truncated,
                )
            ),
            *coordinator_revision_parts,
        )
        return AttendanceGroupDashboardSummary(
            group_id=group_id,
            group_name=group_name,
            revision=revision,
            activities=activities,
        )

    async def missing_passengers(
        self,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        canonical_session_id: uuid.UUID,
        expected_revision: str,
        cursor: uuid.UUID | None,
        limit: int,
        search: str | None,
    ) -> AttendanceMissingDashboardPage:
        before = await self._repository.group_aggregate(
            agency_id=agency_id,
            group_id=group_id,
        )
        before_activity = _find_activity(before, canonical_session_id)
        revision = _activity_revision(before, before_activity)
        if revision != expected_revision:
            raise AttendanceSnapshotChangedError

        page = await self._repository.missing_passengers(
            agency_id=agency_id,
            group_id=group_id,
            canonical_session_id=canonical_session_id,
            cursor=cursor,
            limit=limit,
            search=search,
        )

        # READ COMMITTED intentionally does not block field scanners.  The
        # second aggregate read provides an optimistic snapshot fence: if a
        # scan or roster mutation committed during pagination, the caller
        # receives a stable conflict code and restarts from the new revision.
        after = await self._repository.group_aggregate(
            agency_id=agency_id,
            group_id=group_id,
        )
        after_activity = _find_activity(after, canonical_session_id)
        if _activity_revision(after, after_activity) != revision:
            raise AttendanceSnapshotChangedError

        return AttendanceMissingDashboardPage(
            session_id=canonical_session_id,
            revision=revision,
            page=page,
        )


def _visible_coordinator_ids(
    statuses: Mapping[uuid.UUID, AttendanceCloseoutStatus],
) -> tuple[uuid.UUID, ...]:
    names: dict[uuid.UUID, str] = {}
    for status in statuses.values():
        for coordinator in status.coordinators:
            existing = names.get(coordinator.coordinator_id)
            if existing is None or coordinator.coordinator_name.casefold() < existing.casefold():
                names[coordinator.coordinator_id] = coordinator.coordinator_name
    ordered = sorted(
        names,
        key=lambda coordinator_id: (
            names[coordinator_id].casefold(),
            str(coordinator_id),
        ),
    )
    return tuple(ordered[:MAX_ATTENDANCE_SUMMARY_COORDINATORS])


__all__ = [
    "AttendanceActivityDashboardSummary",
    "AttendanceActivityNotFoundError",
    "AttendanceDashboardService",
    "AttendanceCoordinatorDashboardSummary",
    "AttendanceGroupDashboardSummary",
    "AttendanceMissingDashboardPage",
    "AttendanceSnapshotChangedError",
]
