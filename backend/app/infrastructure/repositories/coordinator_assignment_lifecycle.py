"""Bounded coordinator expiry that preserves trips, documents and assignment history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Date, and_, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.domain.value_objects.trip_timezone import DEFAULT_TRIP_TIMEZONE
from app.infrastructure.database.models import (
    ClientGroupModel,
    CoordinatorAssignmentModel,
    CoordinatorGroupAssignmentModel,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository

COORDINATOR_EXPIRY_GROUP_BATCH_SIZE = 100


def _trip_local_date(now: datetime | None, group_model: Any) -> Any:
    timestamp = now or datetime.now(tz=UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Trip lifecycle checks require a timezone-aware timestamp")
    timezone = func.coalesce(
        func.nullif(func.trim(group_model.timezone), ""), DEFAULT_TRIP_TIMEZONE
    )
    return func.date(func.timezone(timezone, timestamp.astimezone(UTC)), type_=Date)


def expired_trip_clause(
    now: datetime | None = None,
    *,
    group_model: Any = ClientGroupModel,
) -> ColumnElement[bool]:
    """Trips strictly past their local end date; undated groups are false."""

    end_date = func.coalesce(group_model.return_date, group_model.travel_date)
    return and_(end_date.is_not(None), end_date < _trip_local_date(now, group_model))


def current_trip_clause(
    now: datetime | None = None,
    *,
    group_model: Any = ClientGroupModel,
) -> ColumnElement[bool]:
    """Dated upcoming/in-progress trips that can receive new assignments."""

    end_date = func.coalesce(group_model.return_date, group_model.travel_date)
    return and_(end_date.is_not(None), end_date >= _trip_local_date(now, group_model))


@dataclass(frozen=True, slots=True)
class CoordinatorAssignmentExpiryResult:
    groups: int = 0
    group_assignments: int = 0
    passenger_assignments: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "groups": self.groups,
            "group_assignments": self.group_assignments,
            "passenger_assignments": self.passenger_assignments,
        }


async def expire_coordinator_assignments(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    batch_size: int = COORDINATOR_EXPIRY_GROUP_BATCH_SIZE,
) -> CoordinatorAssignmentExpiryResult:
    """Deactivate one page in the caller's transaction, without deleting rows.

    Lock group rows before assignment rows, matching the assignment writer.
    SKIP LOCKED lets overlapping worker deliveries safely process other groups.
    Date checks in authorization close access immediately even before Beat runs.
    """

    if not 1 <= batch_size <= COORDINATOR_EXPIRY_GROUP_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {COORDINATOR_EXPIRY_GROUP_BATCH_SIZE}")
    timestamp = now or datetime.now(tz=UTC)
    assignment_models = (CoordinatorGroupAssignmentModel, CoordinatorAssignmentModel)
    has_active_assignments = or_(
        *(
            exists().where(
                model.group_id == ClientGroupModel.id,
                model.agency_id == ClientGroupModel.agency_id,
                model.active.is_(True),
            )
            for model in assignment_models
        )
    )
    groups = (
        (
            await session.execute(
                select(ClientGroupModel)
                .where(expired_trip_clause(timestamp), has_active_assignments)
                # Consistent agency order also avoids inverted audit-chain locks.
                .order_by(
                    ClientGroupModel.agency_id,
                    func.coalesce(ClientGroupModel.return_date, ClientGroupModel.travel_date),
                    ClientGroupModel.id,
                )
                .limit(batch_size)
                .with_for_update(skip_locked=True, of=ClientGroupModel)
            )
        )
        .scalars()
        .all()
    )
    total_groups = total_group_assignments = total_passenger_assignments = 0
    audit = AuditLogRepository(session)
    for group in groups:
        counts = []
        for model in assignment_models:
            result = await session.execute(
                update(model)
                .where(
                    model.agency_id == group.agency_id,
                    model.group_id == group.id,
                    model.active.is_(True),
                )
                .values(active=False, unassigned_at=timestamp)
                .execution_options(synchronize_session="fetch")
            )
            counts.append(int(getattr(result, "rowcount", 0) or 0))
        if not any(counts):
            continue
        total_groups += 1
        total_group_assignments += counts[0]
        total_passenger_assignments += counts[1]
        end_date = group.return_date or group.travel_date
        assert end_date is not None  # The locked query excludes undated groups.
        await audit.record(
            action="coordinator_assignments_expired",
            entity_type="client_group",
            entity_id=str(group.id),
            agency_id=group.agency_id,
            metadata={
                "reason": "trip_ended",
                "trip_end_date": end_date.isoformat(),
                "timezone": group.timezone,
                "unassigned_at": timestamp.isoformat(),
                "group_assignments": counts[0],
                "passenger_assignments": counts[1],
            },
        )
    return CoordinatorAssignmentExpiryResult(
        groups=total_groups,
        group_assignments=total_group_assignments,
        passenger_assignments=total_passenger_assignments,
    )
