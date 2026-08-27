from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.use_cases.attendance_dashboard import (
    AttendanceActivityDashboardSummary,
    AttendanceActivityNotFoundError,
    AttendanceCloseoutAggregate,
    AttendanceCoordinatorDashboardSummary,
    AttendanceDashboardService,
    AttendanceGroupDashboardSummary,
    AttendanceSnapshotChangedError,
)
from app.presentation.api.v1.routes.tour_operations import (
    _etag_matches,
    get_group_attendance_missing_passengers,
    get_group_attendance_summary,
)


def _request(*, if_none_match: str | None = None) -> Request:
    headers = [] if if_none_match is None else [(b"if-none-match", if_none_match.encode())]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/tour-operations/groups/group/attendance/summary",
            "query_string": b"",
            "headers": headers,
        }
    )


@pytest.mark.parametrize(
    ("header", "matches"),
    [
        (None, False),
        ('"abc"', True),
        ('W/"abc"', True),
        ('"other", W/"abc"', True),
        ("*", True),
        ('"other"', False),
    ],
)
def test_etag_matching_supports_standard_weak_and_list_forms(
    header: str | None,
    matches: bool,
) -> None:
    assert _etag_matches(header, '"abc"') is matches


@pytest.mark.asyncio
async def test_unchanged_summary_returns_304_without_serializing_a_roster() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    projection = AttendanceGroupDashboardSummary(
        group_id=group_id,
        group_name="Enterprise group",
        revision="a" * 32,
        activities=(),
    )
    current_user = SimpleNamespace(agency_id=agency_id)
    group = SimpleNamespace(id=group_id, name="Enterprise group")

    with (
        patch(
            "app.presentation.api.v1.routes.tour_operations._get_manageable_group",
            new=AsyncMock(return_value=group),
        ),
        patch.object(
            AttendanceDashboardService,
            "summary",
            new=AsyncMock(return_value=projection),
        ),
    ):
        result = await get_group_attendance_summary(
            group_id=group_id,
            request=_request(if_none_match='W/"' + "a" * 32 + '"'),
            response=Response(),
            current_user=current_user,
            session=cast(AsyncSession, object()),
        )

    assert isinstance(result, Response)
    assert result.status_code == 304
    assert result.headers["etag"] == '"' + "a" * 32 + '"'
    assert result.body == b""


@pytest.mark.asyncio
async def test_summary_maps_bounded_coordinator_counts_and_checkpoint_state() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    session_id = uuid.uuid4()
    coordinator_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    projection = AttendanceGroupDashboardSummary(
        group_id=group_id,
        group_name="Enterprise group",
        revision="a" * 32,
        activities=(
            AttendanceActivityDashboardSummary(
                session_id=session_id,
                name="Airport reporting",
                status="active",
                revision="b" * 32,
                present_count=745,
                missing_count=55,
                exception_count=3,
                closeout=AttendanceCloseoutAggregate(
                    ready=False,
                    active_participant_count=1,
                    ready_participant_count=0,
                    blocked_participant_count=1,
                    missing_participant_count=0,
                    stale_participant_count=0,
                    unresolved_count=3,
                ),
                coordinator_count=1,
                coordinators_truncated=False,
                coordinators=(
                    AttendanceCoordinatorDashboardSummary(
                        coordinator_id=coordinator_id,
                        coordinator_name="Field coordinator",
                        assigned_count=800,
                        scanned_count=745,
                        checkpoint_state="blocked",
                        checkpoint_reported_at=now,
                        pending_count=0,
                        sending_count=0,
                        retryable_count=0,
                        needs_review_count=2,
                        unreviewed_rejected_count=1,
                        oldest_pending_age_seconds=None,
                        runtime_count=1,
                        active_runtime_count=1,
                    ),
                ),
                last_canonical_update_at=now,
                started_at=now,
                completed_at=None,
            ),
        ),
    )
    current_user = SimpleNamespace(agency_id=agency_id)
    group = SimpleNamespace(id=group_id, name="Enterprise group")

    with (
        patch(
            "app.presentation.api.v1.routes.tour_operations._get_manageable_group",
            new=AsyncMock(return_value=group),
        ),
        patch.object(
            AttendanceDashboardService,
            "summary",
            new=AsyncMock(return_value=projection),
        ),
    ):
        result = await get_group_attendance_summary(
            group_id=group_id,
            request=_request(),
            response=Response(),
            current_user=current_user,
            session=cast(AsyncSession, object()),
        )

    assert not isinstance(result, Response)
    assert result.sessions[0].coordinator_count == 1
    assert result.sessions[0].coordinators_truncated is False
    coordinator = result.sessions[0].coordinators[0]
    assert coordinator.coordinator_id == coordinator_id
    assert coordinator.assigned_count == 800
    assert coordinator.scanned_count == 745
    assert coordinator.checkpoint_state == "blocked"
    assert coordinator.needs_review_count == 2
    assert coordinator.unreviewed_rejected_count == 1


@pytest.mark.asyncio
async def test_changed_missing_snapshot_has_a_stable_typed_conflict() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    current_user = SimpleNamespace(agency_id=agency_id)
    group = SimpleNamespace(id=group_id)

    with (
        patch(
            "app.presentation.api.v1.routes.tour_operations._get_manageable_group",
            new=AsyncMock(return_value=group),
        ),
        patch.object(
            AttendanceDashboardService,
            "missing_passengers",
            new=AsyncMock(side_effect=AttendanceSnapshotChangedError),
        ),
    ):
        response = await get_group_attendance_missing_passengers(
            group_id=group_id,
            session_id=uuid.uuid4(),
            revision="a" * 32,
            cursor=None,
            limit=50,
            search=None,
            current_user=current_user,
            session=cast(AsyncSession, object()),
        )

    assert response.status_code == 409
    assert json.loads(response.body)["error"] == {
        "code": "ATTENDANCE_SNAPSHOT_CHANGED",
        "message": (
            "Attendance changed while this page was loading. "
            "Refresh the activity before continuing."
        ),
    }


@pytest.mark.asyncio
async def test_out_of_scope_activity_uses_the_same_generic_not_found_response() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    current_user = SimpleNamespace(agency_id=agency_id)
    group = SimpleNamespace(id=group_id)

    with (
        patch(
            "app.presentation.api.v1.routes.tour_operations._get_manageable_group",
            new=AsyncMock(return_value=group),
        ),
        patch.object(
            AttendanceDashboardService,
            "missing_passengers",
            new=AsyncMock(side_effect=AttendanceActivityNotFoundError),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await get_group_attendance_missing_passengers(
            group_id=group_id,
            session_id=uuid.uuid4(),
            revision="a" * 32,
            cursor=None,
            limit=50,
            search=None,
            current_user=current_user,
            session=cast(AsyncSession, object()),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Attendance activity was not found"
