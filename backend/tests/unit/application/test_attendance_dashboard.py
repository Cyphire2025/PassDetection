from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.application.use_cases.attendance_dashboard import (
    AttendanceActivityNotFoundError,
    AttendanceDashboardService,
    AttendanceSnapshotChangedError,
)
from app.infrastructure.repositories.attendance_closeout_repository import (
    AttendanceCloseoutCoordinatorStatus,
    AttendanceCloseoutRepository,
    AttendanceCloseoutStatus,
)
from app.infrastructure.repositories.attendance_dashboard_repository import (
    AttendanceActivityAggregate,
    AttendanceCoordinatorScanAggregate,
    AttendanceDashboardRepository,
    AttendanceGroupAggregate,
    AttendanceRosterAggregate,
    MissingPassengerPage,
    MissingPassengerProjection,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    AttendanceActivitySummaryResponse,
    AttendanceSummaryCloseout,
    GroupAttendanceSummaryResponse,
)

NOW = datetime(2026, 8, 23, 10, 0, tzinfo=UTC)
AGENCY_ID = uuid.UUID("10000000-0000-0000-0000-000000000001")
GROUP_ID = uuid.UUID("20000000-0000-0000-0000-000000000001")
SESSION_ID = uuid.UUID("30000000-0000-0000-0000-000000000001")


class _DashboardRepositoryStub(AttendanceDashboardRepository):
    def __init__(
        self,
        aggregates: list[AttendanceGroupAggregate],
        *,
        missing_page: MissingPassengerPage | None = None,
        coordinator_scans: tuple[AttendanceCoordinatorScanAggregate, ...] = (),
    ) -> None:
        self.aggregates = aggregates
        self.missing_page = missing_page or MissingPassengerPage((), False, None)
        self.coordinator_scans = coordinator_scans
        self.aggregate_calls = 0
        self.missing_calls = 0
        self.requested_coordinator_ids: tuple[uuid.UUID, ...] = ()

    async def group_aggregate(
        self,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
    ) -> AttendanceGroupAggregate:
        assert agency_id == AGENCY_ID
        assert group_id == GROUP_ID
        index = min(self.aggregate_calls, len(self.aggregates) - 1)
        self.aggregate_calls += 1
        return self.aggregates[index]

    async def missing_passengers(
        self,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        canonical_session_id: uuid.UUID,
        cursor: uuid.UUID | None,
        limit: int,
        search: str | None,
    ) -> MissingPassengerPage:
        assert agency_id == AGENCY_ID
        assert group_id == GROUP_ID
        assert canonical_session_id == SESSION_ID
        assert limit == 50
        self.missing_calls += 1
        return self.missing_page

    async def coordinator_scan_counts(
        self,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        session_ids: tuple[uuid.UUID, ...],
        coordinator_ids: tuple[uuid.UUID, ...],
    ) -> tuple[AttendanceCoordinatorScanAggregate, ...]:
        assert agency_id == AGENCY_ID
        assert group_id == GROUP_ID
        assert session_ids == (SESSION_ID,)
        self.requested_coordinator_ids = coordinator_ids
        return self.coordinator_scans


class _CloseoutRepositoryStub(AttendanceCloseoutRepository):
    def __init__(self, status: AttendanceCloseoutStatus) -> None:
        self.status = status
        self.calls: list[Mapping[uuid.UUID, datetime]] = []

    async def statuses(
        self,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        activity_valid_after: Mapping[uuid.UUID, datetime],
        now: datetime | None = None,
    ) -> dict[uuid.UUID, AttendanceCloseoutStatus]:
        assert agency_id == AGENCY_ID
        assert group_id == GROUP_ID
        self.calls.append(activity_valid_after)
        return {SESSION_ID: self.status}


def _aggregate(
    *,
    present_count: int = 745,
    record_count: int = 750,
    roster_count: int = 800,
) -> AttendanceGroupAggregate:
    return AttendanceGroupAggregate(
        roster=AttendanceRosterAggregate(
            passenger_count=roster_count,
            latest_updated_at=NOW - timedelta(minutes=1),
            latest_passenger_key="ffffffff-ffff-ffff-ffff-ffffffffffff",
        ),
        activities=(
            AttendanceActivityAggregate(
                session_id=SESSION_ID,
                name="Airport reporting",
                status="active",
                created_at=NOW - timedelta(hours=2),
                started_at=NOW - timedelta(hours=1),
                completed_at=None,
                updated_at=NOW - timedelta(minutes=5),
                present_count=present_count,
                record_count=record_count,
                latest_record_created_at=NOW - timedelta(seconds=2),
            ),
        ),
    )


def _closeout_status() -> AttendanceCloseoutStatus:
    coordinator = AttendanceCloseoutCoordinatorStatus(
        coordinator_id=uuid.uuid4(),
        coordinator_name="Coordinator",
        state="blocked",
        reported_at=NOW - timedelta(seconds=5),
        report_age_seconds=5,
        pending_count=0,
        sending_count=0,
        retryable_count=0,
        needs_review_count=2,
        unreviewed_rejected_count=1,
        oldest_pending_age_seconds=None,
        runtime_id=uuid.uuid4(),
        runtime_kind="browser_pwa",
        runtime_status="active",
    )
    return AttendanceCloseoutStatus(
        ready=False,
        checkpoint_ttl_seconds=120,
        active_assignment_count=2,
        ready_assignment_count=1,
        missing_assignment_count=0,
        stale_assignment_count=0,
        nonzero_assignment_count=1,
        blocked_assignment_count=1,
        unresolved_count=3,
        oldest_pending_age_seconds=None,
        coordinators=(coordinator,),
    )


@pytest.mark.asyncio
async def test_summary_is_count_only_authoritative_and_revisioned() -> None:
    closeout_status = _closeout_status()
    coordinator_id = closeout_status.coordinators[0].coordinator_id
    repository = _DashboardRepositoryStub(
        [_aggregate()],
        coordinator_scans=(
            AttendanceCoordinatorScanAggregate(
                session_id=SESSION_ID,
                coordinator_id=coordinator_id,
                scanned_count=123,
            ),
        ),
    )
    closeout = _CloseoutRepositoryStub(closeout_status)

    result = await AttendanceDashboardService(repository, closeout).summary(
        agency_id=AGENCY_ID,
        group_id=GROUP_ID,
        group_name="Enterprise group",
    )

    assert len(result.revision) == 32
    assert len(result.activities) == 1
    activity = result.activities[0]
    assert activity.present_count == 745
    assert activity.missing_count == 55
    assert activity.exception_count == 3
    assert activity.closeout.active_participant_count == 2
    assert activity.closeout.blocked_participant_count == 1
    assert activity.coordinator_count == 1
    assert activity.coordinators_truncated is False
    assert len(activity.coordinators) == 1
    coordinator = activity.coordinators[0]
    assert coordinator.coordinator_id == coordinator_id
    assert coordinator.assigned_count == 800
    assert coordinator.scanned_count == 123
    assert coordinator.checkpoint_state == "blocked"
    assert coordinator.needs_review_count == 2
    assert coordinator.unreviewed_rejected_count == 1
    assert coordinator.runtime_count == 1
    assert activity.last_canonical_update_at == NOW - timedelta(seconds=2)
    assert closeout.calls == [{SESSION_ID: NOW - timedelta(hours=1)}]


@pytest.mark.asyncio
async def test_coordinator_projection_is_deterministically_capped_at_twenty_five() -> None:
    coordinator_statuses = tuple(
        AttendanceCloseoutCoordinatorStatus(
            coordinator_id=uuid.UUID(int=index + 1),
            coordinator_name=f"Coordinator {index:02d}",
            state="missing",
            reported_at=None,
            report_age_seconds=None,
            pending_count=0,
            sending_count=0,
            retryable_count=0,
            needs_review_count=0,
            unreviewed_rejected_count=0,
            oldest_pending_age_seconds=None,
            runtime_id=None,
            runtime_kind="legacy_account",
            runtime_status="active",
        )
        for index in range(30)
    )
    closeout = AttendanceCloseoutStatus(
        ready=False,
        checkpoint_ttl_seconds=120,
        active_assignment_count=30,
        ready_assignment_count=0,
        missing_assignment_count=30,
        stale_assignment_count=0,
        nonzero_assignment_count=0,
        blocked_assignment_count=30,
        unresolved_count=0,
        oldest_pending_age_seconds=None,
        coordinators=coordinator_statuses,
    )
    repository = _DashboardRepositoryStub([_aggregate()])

    result = await AttendanceDashboardService(
        repository,
        _CloseoutRepositoryStub(closeout),
    ).summary(
        agency_id=AGENCY_ID,
        group_id=GROUP_ID,
        group_name="Enterprise group",
    )

    activity = result.activities[0]
    assert activity.coordinator_count == 30
    assert activity.coordinators_truncated is True
    assert len(activity.coordinators) == 25
    assert len(repository.requested_coordinator_ids) == 25
    assert [item.coordinator_name for item in activity.coordinators] == [
        f"Coordinator {index:02d}" for index in range(25)
    ]


@pytest.mark.asyncio
async def test_pending_age_and_etag_remain_stable_as_checkpoint_time_elapses() -> None:
    initial = _closeout_status()
    initial_coordinator = replace(
        initial.coordinators[0],
        report_age_seconds=5,
        pending_count=1,
        needs_review_count=0,
        unreviewed_rejected_count=0,
        oldest_pending_age_seconds=35,
    )
    initial = replace(
        initial,
        unresolved_count=1,
        oldest_pending_age_seconds=35,
        coordinators=(initial_coordinator,),
    )
    elapsed_coordinator = replace(
        initial_coordinator,
        report_age_seconds=25,
        oldest_pending_age_seconds=55,
    )
    elapsed = replace(
        initial,
        oldest_pending_age_seconds=55,
        coordinators=(elapsed_coordinator,),
    )

    first = await AttendanceDashboardService(
        _DashboardRepositoryStub([_aggregate()]),
        _CloseoutRepositoryStub(initial),
    ).summary(agency_id=AGENCY_ID, group_id=GROUP_ID, group_name="Enterprise group")
    later = await AttendanceDashboardService(
        _DashboardRepositoryStub([_aggregate()]),
        _CloseoutRepositoryStub(elapsed),
    ).summary(agency_id=AGENCY_ID, group_id=GROUP_ID, group_name="Enterprise group")

    assert first.activities[0].coordinators[0].oldest_pending_age_seconds == 30
    assert later.activities[0].coordinators[0].oldest_pending_age_seconds == 30
    assert later.revision == first.revision


@pytest.mark.asyncio
async def test_revision_is_stable_for_identical_state_and_changes_with_canonical_records() -> None:
    closeout = _CloseoutRepositoryStub(_closeout_status())
    service = AttendanceDashboardService(
        _DashboardRepositoryStub([_aggregate(), _aggregate(record_count=751)]),
        closeout,
    )

    first = await service.summary(
        agency_id=AGENCY_ID,
        group_id=GROUP_ID,
        group_name="Enterprise group",
    )
    second = await service.summary(
        agency_id=AGENCY_ID,
        group_id=GROUP_ID,
        group_name="Enterprise group",
    )

    assert first.activities[0].revision != second.activities[0].revision
    assert first.revision != second.revision


@pytest.mark.asyncio
async def test_missing_page_is_fenced_before_and_after_the_bounded_query() -> None:
    passenger_id = uuid.uuid4()
    aggregate = _aggregate()
    repository = _DashboardRepositoryStub(
        [aggregate, aggregate],
        missing_page=MissingPassengerPage(
            (MissingPassengerProjection(passenger_id, "Passenger 746"),),
            False,
            None,
        ),
    )
    service = AttendanceDashboardService(repository, _CloseoutRepositoryStub(_closeout_status()))
    summary = await AttendanceDashboardService(
        _DashboardRepositoryStub([aggregate]),
        _CloseoutRepositoryStub(_closeout_status()),
    ).summary(agency_id=AGENCY_ID, group_id=GROUP_ID, group_name="Enterprise group")

    page = await service.missing_passengers(
        agency_id=AGENCY_ID,
        group_id=GROUP_ID,
        canonical_session_id=SESSION_ID,
        expected_revision=summary.activities[0].revision,
        cursor=None,
        limit=50,
        search=None,
    )

    assert page.page.items[0].passenger_id == passenger_id
    assert repository.aggregate_calls == 2
    assert repository.missing_calls == 1


@pytest.mark.asyncio
async def test_stale_revision_never_reads_passenger_rows() -> None:
    repository = _DashboardRepositoryStub([_aggregate()])
    service = AttendanceDashboardService(repository, _CloseoutRepositoryStub(_closeout_status()))

    with pytest.raises(AttendanceSnapshotChangedError):
        await service.missing_passengers(
            agency_id=AGENCY_ID,
            group_id=GROUP_ID,
            canonical_session_id=SESSION_ID,
            expected_revision="0" * 32,
            cursor=None,
            limit=50,
            search=None,
        )

    assert repository.missing_calls == 0


@pytest.mark.asyncio
async def test_concurrent_scan_invalidates_a_page_instead_of_mixing_snapshots() -> None:
    first = _aggregate()
    after_scan = _aggregate(present_count=746, record_count=751)
    summary = await AttendanceDashboardService(
        _DashboardRepositoryStub([first]),
        _CloseoutRepositoryStub(_closeout_status()),
    ).summary(agency_id=AGENCY_ID, group_id=GROUP_ID, group_name="Enterprise group")
    repository = _DashboardRepositoryStub([first, after_scan])

    with pytest.raises(AttendanceSnapshotChangedError):
        await AttendanceDashboardService(
            repository,
            _CloseoutRepositoryStub(_closeout_status()),
        ).missing_passengers(
            agency_id=AGENCY_ID,
            group_id=GROUP_ID,
            canonical_session_id=SESSION_ID,
            expected_revision=summary.activities[0].revision,
            cursor=None,
            limit=50,
            search=None,
        )

    assert repository.missing_calls == 1


@pytest.mark.asyncio
async def test_unknown_activity_is_indistinguishable_from_an_out_of_scope_activity() -> None:
    repository = _DashboardRepositoryStub([_aggregate()])

    with pytest.raises(AttendanceActivityNotFoundError):
        await AttendanceDashboardService(
            repository,
            _CloseoutRepositoryStub(_closeout_status()),
        ).missing_passengers(
            agency_id=AGENCY_ID,
            group_id=GROUP_ID,
            canonical_session_id=uuid.uuid4(),
            expected_revision="0" * 32,
            cursor=None,
            limit=50,
            search=None,
        )


def test_summary_contract_is_dramatically_smaller_than_an_800_person_roster() -> None:
    summary = GroupAttendanceSummaryResponse(
        group_id=GROUP_ID,
        group_name="Enterprise group",
        revision="a" * 32,
        sessions=[
            AttendanceActivitySummaryResponse(
                id=SESSION_ID,
                name="Airport reporting",
                status="active",
                revision="b" * 32,
                present_count=745,
                missing_count=55,
                exception_count=3,
                closeout=AttendanceSummaryCloseout(
                    ready=False,
                    active_participant_count=2,
                    ready_participant_count=1,
                    blocked_participant_count=1,
                    missing_participant_count=0,
                    stale_participant_count=0,
                    unresolved_count=3,
                ),
                last_canonical_update_at=NOW,
            )
        ],
    )
    summary_payload = summary.model_dump_json()
    legacy_payload = json.dumps(
        {
            "missing_passengers": [
                {
                    "passenger_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"passenger-{index}")),
                    "client_name": f"Passenger {index}",
                    "client_email": f"passenger-{index}@example.test",
                    "client_phone": f"+910000{index:04d}",
                    "departure_city": "Delhi",
                }
                for index in range(800)
            ]
        }
    )

    assert len(summary_payload.encode("utf-8")) < 2_500
    assert len(legacy_payload.encode("utf-8")) > len(summary_payload.encode("utf-8")) * 100
    for forbidden in (
        "client_email",
        "client_phone",
        "departure_city",
        "missing_passengers",
    ):
        assert forbidden not in summary_payload
