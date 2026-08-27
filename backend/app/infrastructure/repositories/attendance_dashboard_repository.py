"""Bounded attendance projections for office dashboards.

The legacy attendance overview intentionally remains available for older
dashboard builds.  New dashboard polling uses this repository so a refresh
reads aggregate state only; passenger rows are read solely by the explicit,
paginated missing-passenger view.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import String, cast, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.domain.entities.entities import (
    OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES,
)
from app.infrastructure.database.models import (
    AttendanceRecordModel,
    AttendanceSessionModel,
    PassportSubmissionModel,
)

MAX_ATTENDANCE_SUMMARY_COORDINATORS = 25


@dataclass(frozen=True, slots=True)
class AttendanceRosterAggregate:
    passenger_count: int
    latest_updated_at: datetime | None
    latest_passenger_key: str | None


@dataclass(frozen=True, slots=True)
class AttendanceActivityAggregate:
    session_id: uuid.UUID
    name: str
    status: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    updated_at: datetime
    present_count: int
    record_count: int
    latest_record_created_at: datetime | None


@dataclass(frozen=True, slots=True)
class AttendanceGroupAggregate:
    roster: AttendanceRosterAggregate
    activities: tuple[AttendanceActivityAggregate, ...]


@dataclass(frozen=True, slots=True)
class AttendanceCoordinatorScanAggregate:
    session_id: uuid.UUID
    coordinator_id: uuid.UUID
    scanned_count: int


@dataclass(frozen=True, slots=True)
class MissingPassengerProjection:
    passenger_id: uuid.UUID
    display_name: str


@dataclass(frozen=True, slots=True)
class MissingPassengerPage:
    items: tuple[MissingPassengerProjection, ...]
    has_more: bool
    next_cursor: uuid.UUID | None


class AttendanceDashboardRepository:
    """Read-only, tenant-scoped dashboard queries with fixed query count."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def group_aggregate(
        self,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
    ) -> AttendanceGroupAggregate:
        sessions_result = await self._session.execute(
            select(AttendanceSessionModel)
            .where(
                AttendanceSessionModel.agency_id == agency_id,
                AttendanceSessionModel.group_id == group_id,
                AttendanceSessionModel.id == AttendanceSessionModel.canonical_session_id,
            )
            .order_by(
                AttendanceSessionModel.created_at.desc(),
                AttendanceSessionModel.id.desc(),
            )
        )
        sessions = tuple(sessions_result.scalars().all())

        roster_row = (
            await self._session.execute(
                select(
                    func.count(PassportSubmissionModel.id).label("passenger_count"),
                    func.max(PassportSubmissionModel.updated_at).label("latest_updated_at"),
                    func.max(cast(PassportSubmissionModel.id, String)).label(
                        "latest_passenger_key"
                    ),
                ).where(
                    PassportSubmissionModel.agency_id == agency_id,
                    PassportSubmissionModel.group_id == group_id,
                    PassportSubmissionModel.status.in_(
                        OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
                    ),
                )
            )
        ).one()
        roster = AttendanceRosterAggregate(
            passenger_count=int(roster_row.passenger_count or 0),
            latest_updated_at=roster_row.latest_updated_at,
            latest_passenger_key=roster_row.latest_passenger_key,
        )
        if not sessions:
            return AttendanceGroupAggregate(roster=roster, activities=())

        session_ids = tuple(item.id for item in sessions)
        family_session = aliased(
            AttendanceSessionModel,
            name="attendance_dashboard_family",
        )
        attendance_rows = (
            await self._session.execute(
                select(
                    family_session.canonical_session_id.label("canonical_session_id"),
                    func.count(func.distinct(AttendanceRecordModel.passenger_id)).label(
                        "present_count"
                    ),
                    func.count(AttendanceRecordModel.id).label("record_count"),
                    func.max(AttendanceRecordModel.created_at).label("latest_record_created_at"),
                )
                .select_from(AttendanceRecordModel)
                .join(
                    family_session,
                    family_session.id == AttendanceRecordModel.session_id,
                )
                .where(
                    AttendanceRecordModel.agency_id == agency_id,
                    family_session.agency_id == agency_id,
                    family_session.group_id == group_id,
                    family_session.canonical_session_id.in_(session_ids),
                )
                .group_by(family_session.canonical_session_id)
            )
        ).all()
        attendance_by_session = {row.canonical_session_id: row for row in attendance_rows}

        activities: list[AttendanceActivityAggregate] = []
        for attendance_session in sessions:
            attendance = attendance_by_session.get(attendance_session.id)
            activities.append(
                AttendanceActivityAggregate(
                    session_id=attendance_session.id,
                    name=attendance_session.name,
                    status=attendance_session.status,
                    created_at=attendance_session.created_at,
                    started_at=attendance_session.started_at,
                    completed_at=attendance_session.completed_at,
                    updated_at=attendance_session.updated_at,
                    present_count=int(attendance.present_count or 0)
                    if attendance is not None
                    else 0,
                    record_count=int(attendance.record_count or 0) if attendance is not None else 0,
                    latest_record_created_at=attendance.latest_record_created_at
                    if attendance is not None
                    else None,
                )
            )
        return AttendanceGroupAggregate(roster=roster, activities=tuple(activities))

    async def coordinator_scan_counts(
        self,
        *,
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
        session_ids: tuple[uuid.UUID, ...],
        coordinator_ids: tuple[uuid.UUID, ...],
    ) -> tuple[AttendanceCoordinatorScanAggregate, ...]:
        """Count first canonical scans for a bounded coordinator projection."""

        if len(coordinator_ids) > MAX_ATTENDANCE_SUMMARY_COORDINATORS:
            raise ValueError("Attendance coordinator summary limit exceeded")
        if not session_ids or not coordinator_ids:
            return ()

        family_session = aliased(
            AttendanceSessionModel,
            name="attendance_coordinator_scan_family",
        )
        ranked_records = (
            select(
                family_session.canonical_session_id.label("canonical_session_id"),
                AttendanceRecordModel.passenger_id.label("passenger_id"),
                AttendanceRecordModel.coordinator_user_id.label("coordinator_user_id"),
                func.row_number()
                .over(
                    partition_by=(
                        family_session.canonical_session_id,
                        AttendanceRecordModel.passenger_id,
                    ),
                    order_by=(
                        AttendanceRecordModel.scanned_at.asc(),
                        AttendanceRecordModel.id.asc(),
                    ),
                )
                .label("logical_scan_rank"),
            )
            .select_from(AttendanceRecordModel)
            .join(
                family_session,
                family_session.id == AttendanceRecordModel.session_id,
            )
            .where(
                AttendanceRecordModel.agency_id == agency_id,
                family_session.agency_id == agency_id,
                family_session.group_id == group_id,
                family_session.canonical_session_id.in_(session_ids),
            )
            .subquery()
        )
        rows = (
            await self._session.execute(
                select(
                    ranked_records.c.canonical_session_id,
                    ranked_records.c.coordinator_user_id,
                    func.count().label("scanned_count"),
                )
                .where(
                    ranked_records.c.logical_scan_rank == 1,
                    ranked_records.c.coordinator_user_id.in_(coordinator_ids),
                )
                .group_by(
                    ranked_records.c.canonical_session_id,
                    ranked_records.c.coordinator_user_id,
                )
                .order_by(
                    ranked_records.c.canonical_session_id,
                    ranked_records.c.coordinator_user_id,
                )
            )
        ).all()
        return tuple(
            AttendanceCoordinatorScanAggregate(
                session_id=row.canonical_session_id,
                coordinator_id=row.coordinator_user_id,
                scanned_count=int(row.scanned_count or 0),
            )
            for row in rows
        )

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
        family_session = aliased(
            AttendanceSessionModel,
            name="missing_passenger_attendance_family",
        )
        already_present = (
            select(literal(1))
            .select_from(AttendanceRecordModel)
            .join(
                family_session,
                family_session.id == AttendanceRecordModel.session_id,
            )
            .where(
                AttendanceRecordModel.agency_id == agency_id,
                family_session.agency_id == agency_id,
                family_session.group_id == group_id,
                family_session.canonical_session_id == canonical_session_id,
                AttendanceRecordModel.passenger_id == PassportSubmissionModel.id,
            )
            .exists()
        )
        statement = select(
            PassportSubmissionModel.id.label("passenger_id"),
            PassportSubmissionModel.client_name.label("display_name"),
        ).where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
            PassportSubmissionModel.status.in_(OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES),
            ~already_present,
        )
        if cursor is not None:
            statement = statement.where(PassportSubmissionModel.id > cursor)
        if search:
            statement = statement.where(
                PassportSubmissionModel.client_name.ilike(
                    f"%{_escape_like(search)}%",
                    escape="\\",
                )
            )
        rows = (
            await self._session.execute(
                statement.order_by(PassportSubmissionModel.id.asc()).limit(limit + 1)
            )
        ).all()
        has_more = len(rows) > limit
        visible_rows = rows[:limit]
        items = tuple(
            MissingPassengerProjection(
                passenger_id=row.passenger_id,
                display_name=row.display_name,
            )
            for row in visible_rows
        )
        next_cursor = items[-1].passenger_id if has_more and items else None
        return MissingPassengerPage(
            items=items,
            has_more=has_more,
            next_cursor=next_cursor,
        )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


__all__ = [
    "AttendanceActivityAggregate",
    "AttendanceCoordinatorScanAggregate",
    "AttendanceDashboardRepository",
    "AttendanceGroupAggregate",
    "AttendanceRosterAggregate",
    "MissingPassengerPage",
    "MissingPassengerProjection",
    "MAX_ATTENDANCE_SUMMARY_COORDINATORS",
]
