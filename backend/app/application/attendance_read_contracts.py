"""Application-owned immutable attendance read contracts; no persistence imports."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


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


# Keep published named-import/pickle identities while defining every class once.
AttendanceRosterAggregate.__module__ = (
    "app.infrastructure.repositories.attendance_dashboard_repository"
)
AttendanceActivityAggregate.__module__ = (
    "app.infrastructure.repositories.attendance_dashboard_repository"
)
AttendanceGroupAggregate.__module__ = (
    "app.infrastructure.repositories.attendance_dashboard_repository"
)
AttendanceCoordinatorScanAggregate.__module__ = (
    "app.infrastructure.repositories.attendance_dashboard_repository"
)
MissingPassengerProjection.__module__ = (
    "app.infrastructure.repositories.attendance_dashboard_repository"
)
MissingPassengerPage.__module__ = "app.infrastructure.repositories.attendance_dashboard_repository"
