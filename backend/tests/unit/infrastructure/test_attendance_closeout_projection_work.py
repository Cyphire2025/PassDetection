"""Public closeout projection avoids rereading every event for every activity."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.infrastructure.repositories.attendance_closeout_repository import (
    AttendanceCloseoutRepository,
)

NOW = datetime(2026, 10, 31, 12, tzinfo=UTC)


class _CountedActivityRow:
    def __init__(self, session_id, **fields):
        self._session_id = session_id
        self.activity_reads = 0
        self.__dict__.update(fields)

    @property
    def session_id(self):
        self.activity_reads += 1
        return self._session_id


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return self


class _Session:
    def __init__(self, batches):
        self._batches = iter(batches)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(next(self._batches))


@pytest.mark.parametrize("activity_count", [1, 16])
async def test_public_statuses_preserve_runtime_and_legacy_results_with_linear_source_work(
    activity_count,
):
    agency_id, group_id = uuid.uuid4(), uuid.uuid4()
    coordinators = [uuid.UUID(int=index) for index in range(1, 4)]
    runtimes = [uuid.UUID(int=index) for index in (100, 101)]
    activities = [uuid.UUID(int=1000 + index) for index in range(activity_count)]
    assignments = [
        SimpleNamespace(
            coordinator_user_id=coordinator,
            full_name=f"Synthetic coordinator {index}",
            assigned_at=NOW - timedelta(hours=1),
        )
        for index, coordinator in enumerate(coordinators)
    ]
    checkpoints, participants = [], []
    for index, activity in enumerate(activities):
        for coordinator_index, (coordinator, runtime) in enumerate(
            zip(coordinators, runtimes, strict=False)
        ):
            pending = int(index == coordinator_index == 0)
            checkpoints.append(
                _CountedActivityRow(
                    activity,
                    coordinator_user_id=coordinator,
                    runtime_registration_id=runtime,
                    reported_at=NOW - timedelta(seconds=1),
                    pending_count=pending,
                    sending_count=0,
                    retryable_count=0,
                    needs_review_count=0,
                    unreviewed_rejected_count=0,
                    oldest_pending_age_seconds=8 if pending else None,
                )
            )
            participants.append(
                _CountedActivityRow(
                    activity,
                    coordinator_user_id=coordinator,
                    runtime_registration_id=runtime,
                    first_participated_at=NOW - timedelta(minutes=10),
                    full_name=f"Synthetic coordinator {coordinator_index}",
                    runtime_kind="pwa",
                    runtime_status="active",
                )
            )
    source_runtimes = [
        SimpleNamespace(id=runtime, runtime_kind="pwa", status="active") for runtime in runtimes
    ]
    session = _Session([assignments, checkpoints, source_runtimes, participants])
    # Query authority and actual database behavior are covered separately. The
    # real repository/loader/classifier path is used; only SQL results are fixed
    # so deterministic attribute reads measure projection work, not timing.
    result = await AttendanceCloseoutRepository(session).statuses(
        agency_id=agency_id,
        group_id=group_id,
        activity_valid_after={activity: NOW - timedelta(hours=1) for activity in activities},
        now=NOW,
    )
    assert len(session.statements) == 4
    assert list(result) == activities
    for index, activity in enumerate(activities):
        status = result[activity]
        assert status.ready is False
        assert status.active_assignment_count == 3
        assert status.ready_assignment_count == (1 if index == 0 else 2)
        assert status.missing_assignment_count == 1
        assert status.unresolved_count == (1 if index == 0 else 0)
        assert status.oldest_pending_age_seconds == (9 if index == 0 else None)
        assert [row.coordinator_id for row in status.coordinators] == coordinators
    visits = sum(row.activity_reads for row in [*checkpoints, *participants])
    assert visits <= 8 * (len(checkpoints) + len(participants)), (
        f"{visits} activity-key reads; activity count must not multiply source scans"
    )
