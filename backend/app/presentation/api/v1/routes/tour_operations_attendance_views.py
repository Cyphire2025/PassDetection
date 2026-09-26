"""Attendance views for tour operations; preserve tenant, lock and transaction boundaries."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.infrastructure.database.models import (
    AttendanceRecordModel,
    AttendanceSessionModel,
    ClientGroupModel,
    CoordinatorGroupAssignmentModel,
    PassportSubmissionModel,
    UserModel,
)
from app.infrastructure.repositories.attendance_closeout_repository import (
    AttendanceCloseoutRepository,
)
from app.infrastructure.repositories.operational_roster import operational_roster_member
from app.presentation.api.v1.routes.tour_operations_attendance_projection_support import (
    attendance_activity_valid_after as _attendance_activity_valid_after,
)
from app.presentation.api.v1.routes.tour_operations_attendance_projection_support import (
    attendance_closeout_status_response as _attendance_closeout_status_response,
)
from app.presentation.api.v1.routes.tour_operations_attendance_scan_support import (
    SUBMITTED_PASSENGER_STATUSES,
)
from app.presentation.api.v1.schemas.tour_operations_schemas import (
    AttendanceCoordinatorSummary,
    AttendanceMissingPassenger,
    AttendancePassengerStatus,
    AttendanceScanResponse,
    AttendanceSessionDetailsResponse,
    AttendanceSessionResponse,
    AttendanceSessionSummary,
    GroupAttendanceOverviewResponse,
)


async def _attendance_session_response(
    session: AsyncSession,
    attendance_session: AttendanceSessionModel,
) -> AttendanceSessionResponse:
    counts = await _attendance_counts(
        session,
        attendance_session.id,
        attendance_session.group_id,
    )
    return _session_response(
        attendance_session, scanned_count=counts["scanned"], assigned_count=counts["assigned"]
    )


async def _attendance_session_responses(
    session: AsyncSession,
    attendance_sessions: list[AttendanceSessionModel],
    group_id: uuid.UUID,
) -> list[AttendanceSessionResponse]:
    if not attendance_sessions:
        return []
    assigned_result = await session.execute(
        select(func.count(PassportSubmissionModel.id)).where(
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            operational_roster_member(),
        )
    )
    assigned_count = int(assigned_result.scalar_one() or 0)
    session_ids = [attendance_session.id for attendance_session in attendance_sessions]
    family_session = aliased(
        AttendanceSessionModel,
        name="attendance_session_family",
    )
    scanned_result = await session.execute(
        select(
            family_session.canonical_session_id,
            func.count(func.distinct(AttendanceRecordModel.passenger_id)),
        )
        .select_from(family_session)
        .join(
            AttendanceRecordModel,
            AttendanceRecordModel.session_id == family_session.id,
        )
        .where(family_session.canonical_session_id.in_(session_ids))
        .group_by(family_session.canonical_session_id)
    )
    scanned_counts = {
        session_id: int(scanned_count) for session_id, scanned_count in scanned_result.all()
    }
    return [
        _session_response(
            attendance_session,
            scanned_count=scanned_counts.get(attendance_session.id, 0),
            assigned_count=assigned_count,
        )
        for attendance_session in attendance_sessions
    ]


async def _attendance_scan_response(
    session: AsyncSession,
    attendance_session: AttendanceSessionModel,
    passenger_id: uuid.UUID | None,
    passenger_name: str | None,
    scan_status: str,
    message: str,
) -> AttendanceScanResponse:
    counts = await _attendance_counts(
        session,
        attendance_session.id,
        attendance_session.group_id,
    )
    return AttendanceScanResponse(
        session_id=attendance_session.id,
        passenger_id=passenger_id,
        passenger_name=passenger_name,
        status=scan_status,
        message=message,
        scanned_count=counts["scanned"],
        assigned_count=counts["assigned"],
    )


async def _attendance_session_details_response(
    session: AsyncSession,
    attendance_session: AttendanceSessionModel,
) -> AttendanceSessionDetailsResponse:
    counts = await _attendance_counts(
        session,
        attendance_session.id,
        attendance_session.group_id,
    )
    family_session = aliased(
        AttendanceSessionModel,
        name="attendance_session_family",
    )
    family_scans = (
        select(
            AttendanceRecordModel.passenger_id.label("passenger_id"),
            func.min(AttendanceRecordModel.scanned_at).label("scanned_at"),
        )
        .select_from(AttendanceRecordModel)
        .join(
            family_session,
            family_session.id == AttendanceRecordModel.session_id,
        )
        .where(
            family_session.canonical_session_id == attendance_session.id,
        )
        .group_by(AttendanceRecordModel.passenger_id)
        .subquery()
    )
    passengers_result = await session.execute(
        select(PassportSubmissionModel, family_scans.c.scanned_at)
        .outerjoin(
            family_scans,
            family_scans.c.passenger_id == PassportSubmissionModel.id,
        )
        .where(
            PassportSubmissionModel.agency_id == attendance_session.agency_id,
            PassportSubmissionModel.group_id == attendance_session.group_id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            operational_roster_member(),
        )
        .order_by(PassportSubmissionModel.client_name.asc())
    )
    passenger_statuses = [
        AttendancePassengerStatus(
            passenger_id=passenger.id,
            client_name=passenger.client_name,
            client_email=passenger.client_email,
            client_phone=passenger.client_phone,
            departure_city=passenger.departure_city,
            scanned=scanned_at is not None,
            scanned_at=scanned_at,
        )
        for passenger, scanned_at in passengers_result.all()
    ]
    scanned_passengers = [passenger for passenger in passenger_statuses if passenger.scanned]
    missing_passengers = [passenger for passenger in passenger_statuses if not passenger.scanned]
    return AttendanceSessionDetailsResponse(
        id=attendance_session.id,
        group_id=attendance_session.group_id,
        name=attendance_session.name,
        status=attendance_session.status,
        created_at=attendance_session.created_at,
        started_at=attendance_session.started_at,
        completed_at=attendance_session.completed_at,
        scanned_count=counts["scanned"],
        assigned_count=counts["assigned"],
        missing_passengers=missing_passengers,
        scanned_passengers=scanned_passengers,
        passengers=passenger_statuses,
    )


async def _attendance_counts(
    session: AsyncSession,
    session_id: uuid.UUID,
    group_id: uuid.UUID,
) -> dict[str, int]:
    assigned_count = (
        select(func.count(PassportSubmissionModel.id))
        .where(
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            operational_roster_member(),
        )
        .scalar_subquery()
    )
    family_session = aliased(
        AttendanceSessionModel,
        name="attendance_session_family",
    )
    scanned_count = (
        select(func.count(func.distinct(AttendanceRecordModel.passenger_id)))
        .select_from(AttendanceRecordModel)
        .join(
            family_session,
            family_session.id == AttendanceRecordModel.session_id,
        )
        .where(
            family_session.canonical_session_id == session_id,
        )
        .scalar_subquery()
    )
    counts_result = await session.execute(select(assigned_count, scanned_count))
    assigned, scanned = counts_result.one()
    return {
        "assigned": int(assigned or 0),
        "scanned": int(scanned or 0),
    }


async def _group_attendance_overview(
    session: AsyncSession,
    agency_id: uuid.UUID,
    group: ClientGroupModel,
) -> GroupAttendanceOverviewResponse:
    sessions_result = await session.execute(
        select(AttendanceSessionModel)
        .where(
            AttendanceSessionModel.agency_id == agency_id,
            AttendanceSessionModel.group_id == group.id,
            AttendanceSessionModel.id == AttendanceSessionModel.canonical_session_id,
        )
        .order_by(AttendanceSessionModel.created_at.desc())
    )
    attendance_sessions = list(sessions_result.scalars().all())
    if not attendance_sessions:
        return GroupAttendanceOverviewResponse(
            group_id=group.id, group_name=group.name, sessions=[]
        )

    session_ids = [attendance_session.id for attendance_session in attendance_sessions]
    closeout_statuses = await AttendanceCloseoutRepository(session).statuses(
        agency_id=agency_id,
        group_id=group.id,
        activity_valid_after={
            attendance_session.id: _attendance_activity_valid_after(attendance_session)
            for attendance_session in attendance_sessions
        },
    )
    coordinators_result = await session.execute(
        select(
            CoordinatorGroupAssignmentModel.coordinator_user_id,
            UserModel.full_name,
        )
        .join(UserModel, UserModel.id == CoordinatorGroupAssignmentModel.coordinator_user_id)
        .where(
            CoordinatorGroupAssignmentModel.agency_id == agency_id,
            CoordinatorGroupAssignmentModel.group_id == group.id,
            CoordinatorGroupAssignmentModel.active.is_(True),
        )
        .order_by(UserModel.full_name.asc())
    )
    group_coordinators = {
        row.coordinator_user_id: row.full_name for row in coordinators_result.all()
    }

    passenger_count_result = await session.execute(
        select(func.count(PassportSubmissionModel.id)).where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            operational_roster_member(),
        )
    )
    passenger_count = int(passenger_count_result.scalar_one() or 0)

    family_session = aliased(
        AttendanceSessionModel,
        name="attendance_session_family",
    )
    scanned_result = await session.execute(
        select(
            family_session.canonical_session_id.label("canonical_session_id"),
            AttendanceRecordModel.passenger_id,
            AttendanceRecordModel.coordinator_user_id,
            AttendanceRecordModel.scanned_at,
            AttendanceRecordModel.id.label("attendance_record_id"),
        )
        .select_from(AttendanceRecordModel)
        .join(
            family_session,
            family_session.id == AttendanceRecordModel.session_id,
        )
        .where(family_session.canonical_session_id.in_(session_ids))
        .order_by(
            family_session.canonical_session_id,
            AttendanceRecordModel.passenger_id,
            AttendanceRecordModel.scanned_at,
            AttendanceRecordModel.id,
        )
    )
    scanned_counts: dict[tuple[uuid.UUID, uuid.UUID], int] = defaultdict(int)
    scanned_passenger_ids: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    seen_logical_passengers: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for row in scanned_result.all():
        logical_passenger = (row.canonical_session_id, row.passenger_id)
        if logical_passenger in seen_logical_passengers:
            continue
        seen_logical_passengers.add(logical_passenger)
        scanned_passenger_ids[row.canonical_session_id].add(row.passenger_id)
        scanned_counts[(row.canonical_session_id, row.coordinator_user_id)] += 1

    group_passengers_result = await session.execute(
        select(
            PassportSubmissionModel.id.label("passenger_id"),
            PassportSubmissionModel.client_name,
            PassportSubmissionModel.client_email,
            PassportSubmissionModel.client_phone,
            PassportSubmissionModel.departure_city,
        )
        .where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.status.in_(SUBMITTED_PASSENGER_STATUSES),
            operational_roster_member(),
        )
        .order_by(PassportSubmissionModel.client_name.asc())
    )
    group_passengers = list(group_passengers_result.all())

    summaries: list[AttendanceSessionSummary] = []
    for attendance_session in attendance_sessions:
        coordinators = [
            AttendanceCoordinatorSummary(
                coordinator_id=coordinator_id,
                coordinator_name=name,
                assigned_count=passenger_count,
                scanned_count=scanned_counts.get((attendance_session.id, coordinator_id), 0),
            )
            for coordinator_id, name in group_coordinators.items()
        ]
        missing_passengers = [
            AttendanceMissingPassenger(
                passenger_id=row.passenger_id,
                client_name=row.client_name,
                client_email=row.client_email,
                client_phone=row.client_phone,
                departure_city=row.departure_city,
                coordinator_id=None,
                coordinator_name=None,
            )
            for row in group_passengers
            if row.passenger_id not in scanned_passenger_ids[attendance_session.id]
        ]
        summaries.append(
            AttendanceSessionSummary(
                id=attendance_session.id,
                name=attendance_session.name,
                status=attendance_session.status,
                created_at=attendance_session.created_at,
                started_at=attendance_session.started_at,
                completed_at=attendance_session.completed_at,
                assigned_count=passenger_count,
                scanned_count=len(scanned_passenger_ids[attendance_session.id]),
                coordinators=coordinators,
                missing_passengers=missing_passengers,
                closeout=_attendance_closeout_status_response(
                    closeout_statuses[attendance_session.id]
                ),
            )
        )

    return GroupAttendanceOverviewResponse(
        group_id=group.id, group_name=group.name, sessions=summaries
    )


def _session_response(
    attendance_session: AttendanceSessionModel, *, scanned_count: int, assigned_count: int
) -> AttendanceSessionResponse:
    """Keep single and batched session projections identical without changing queries."""
    return AttendanceSessionResponse(
        id=attendance_session.id,
        group_id=attendance_session.group_id,
        name=attendance_session.name,
        status=attendance_session.status,
        created_at=attendance_session.created_at,
        started_at=attendance_session.started_at,
        completed_at=attendance_session.completed_at,
        scheduled_starts_at=attendance_session.scheduled_starts_at,
        scheduled_ends_at=attendance_session.scheduled_ends_at,
        schedule_timezone=attendance_session.schedule_timezone,
        schedule_version=attendance_session.schedule_version,
        scanned_count=scanned_count,
        assigned_count=assigned_count,
    )
