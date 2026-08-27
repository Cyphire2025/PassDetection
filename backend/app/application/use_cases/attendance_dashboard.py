"""Aggregate attendance projections for the office dashboard."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.infrastructure.repositories.attendance_closeout_repository import (
    AttendanceCloseoutCoordinatorStatus,
    AttendanceCloseoutRepository,
    AttendanceCloseoutStatus,
)
from app.infrastructure.repositories.attendance_dashboard_repository import (
    MAX_ATTENDANCE_SUMMARY_COORDINATORS,
    AttendanceActivityAggregate,
    AttendanceCoordinatorScanAggregate,
    AttendanceDashboardRepository,
    AttendanceGroupAggregate,
    MissingPassengerPage,
)


@dataclass(frozen=True, slots=True)
class AttendanceCloseoutAggregate:
    ready: bool
    active_participant_count: int
    ready_participant_count: int
    blocked_participant_count: int
    missing_participant_count: int
    stale_participant_count: int
    unresolved_count: int


@dataclass(frozen=True, slots=True)
class AttendanceCoordinatorDashboardSummary:
    coordinator_id: uuid.UUID
    coordinator_name: str
    assigned_count: int
    scanned_count: int
    checkpoint_state: Literal["ready", "missing", "stale", "blocked"]
    checkpoint_reported_at: datetime | None
    pending_count: int
    sending_count: int
    retryable_count: int
    needs_review_count: int
    unreviewed_rejected_count: int
    oldest_pending_age_seconds: int | None
    runtime_count: int
    active_runtime_count: int


@dataclass(frozen=True, slots=True)
class AttendanceActivityDashboardSummary:
    session_id: uuid.UUID
    name: str
    status: str
    revision: str
    present_count: int
    missing_count: int
    exception_count: int
    closeout: AttendanceCloseoutAggregate
    coordinator_count: int
    coordinators_truncated: bool
    coordinators: tuple[AttendanceCoordinatorDashboardSummary, ...]
    last_canonical_update_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class AttendanceGroupDashboardSummary:
    group_id: uuid.UUID
    group_name: str
    revision: str
    activities: tuple[AttendanceActivityDashboardSummary, ...]


@dataclass(frozen=True, slots=True)
class AttendanceMissingDashboardPage:
    session_id: uuid.UUID
    revision: str
    page: MissingPassengerPage


class AttendanceActivityNotFoundError(LookupError):
    """The requested canonical activity is outside the authorized group."""


class AttendanceSnapshotChangedError(RuntimeError):
    """The optimistic roster snapshot changed while a page was being read."""


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
            (row.session_id, row.coordinator_id): row.scanned_count
            for row in coordinator_scan_rows
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
        _utc(activity.updated_at),
        *(
            _utc(value)
            for value in (
                group.roster.latest_updated_at,
                activity.latest_record_created_at,
            )
            if value is not None
        ),
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
        unreviewed_rejected_count=sum(
            item.unreviewed_rejected_count for item in statuses
        ),
        oldest_pending_age_seconds=max(oldest_pending) if oldest_pending else None,
        runtime_count=len(statuses),
        active_runtime_count=sum(item.runtime_status == "active" for item in statuses),
    )


def _find_activity(
    group: AttendanceGroupAggregate,
    session_id: uuid.UUID,
) -> AttendanceActivityAggregate:
    activity = next(
        (item for item in group.activities if item.session_id == session_id),
        None,
    )
    if activity is None:
        raise AttendanceActivityNotFoundError
    return activity


def _activity_revision(
    group: AttendanceGroupAggregate,
    activity: AttendanceActivityAggregate,
) -> str:
    return _opaque_revision(
        activity.session_id,
        activity.status,
        activity.updated_at,
        activity.present_count,
        activity.record_count,
        activity.latest_record_created_at,
        group.roster.passenger_count,
        group.roster.latest_updated_at,
        group.roster.latest_passenger_key,
    )


def _opaque_revision(*parts: object) -> str:
    normalized = "|".join(_revision_part(part) for part in parts)
    return hashlib.blake2b(normalized.encode("utf-8"), digest_size=16).hexdigest()


def _revision_part(value: object) -> str:
    if isinstance(value, datetime):
        return _utc(value).isoformat()
    if value is None:
        return "-"
    return str(value)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "AttendanceActivityDashboardSummary",
    "AttendanceActivityNotFoundError",
    "AttendanceDashboardService",
    "AttendanceCoordinatorDashboardSummary",
    "AttendanceGroupDashboardSummary",
    "AttendanceMissingDashboardPage",
    "AttendanceSnapshotChangedError",
]
