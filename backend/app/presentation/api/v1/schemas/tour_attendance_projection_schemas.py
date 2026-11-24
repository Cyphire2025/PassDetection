"""Attendance progress, closeout summaries and paginated passenger projections."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.presentation.api.v1.schemas.attendance_closeout_schemas import (
    AttendanceCloseoutStatusResponse,
)


class AttendancePassengerStatus(BaseModel):
    passenger_id: uuid.UUID
    client_name: str
    client_email: str | None = None
    client_phone: str | None = None
    departure_city: str | None = None
    scanned: bool
    scanned_at: datetime | None = None


class AttendanceSessionDetailsResponse(BaseModel):
    id: uuid.UUID
    group_id: uuid.UUID
    name: str
    status: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    scanned_count: int
    assigned_count: int
    missing_passengers: list[AttendancePassengerStatus] = Field(default_factory=list)
    scanned_passengers: list[AttendancePassengerStatus] = Field(default_factory=list)
    passengers: list[AttendancePassengerStatus] = Field(default_factory=list)


class AttendanceCoordinatorSummary(BaseModel):
    coordinator_id: uuid.UUID
    coordinator_name: str
    assigned_count: int
    scanned_count: int


class AttendanceMissingPassenger(BaseModel):
    passenger_id: uuid.UUID
    client_name: str
    client_email: str | None = None
    client_phone: str | None = None
    departure_city: str | None = None
    coordinator_id: uuid.UUID | None = None
    coordinator_name: str | None = None


class AttendanceSessionSummary(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    assigned_count: int
    scanned_count: int
    coordinators: list[AttendanceCoordinatorSummary] = Field(default_factory=list)
    missing_passengers: list[AttendanceMissingPassenger] = Field(default_factory=list)
    closeout: AttendanceCloseoutStatusResponse


class GroupAttendanceOverviewResponse(BaseModel):
    group_id: uuid.UUID
    group_name: str
    sessions: list[AttendanceSessionSummary] = Field(default_factory=list)


class AttendanceSummaryCloseout(BaseModel):
    ready: bool
    active_participant_count: int = Field(ge=0)
    ready_participant_count: int = Field(ge=0)
    blocked_participant_count: int = Field(ge=0)
    missing_participant_count: int = Field(ge=0)
    stale_participant_count: int = Field(ge=0)
    unresolved_count: int = Field(ge=0)


class AttendanceCoordinatorActivitySummaryResponse(BaseModel):
    coordinator_id: uuid.UUID
    coordinator_name: str = Field(min_length=1, max_length=255)
    assigned_count: int = Field(ge=0)
    scanned_count: int = Field(ge=0)
    checkpoint_state: Literal["ready", "missing", "stale", "blocked"]
    checkpoint_reported_at: datetime | None = None
    pending_count: int = Field(ge=0)
    sending_count: int = Field(ge=0)
    retryable_count: int = Field(ge=0)
    needs_review_count: int = Field(ge=0)
    unreviewed_rejected_count: int = Field(ge=0)
    oldest_pending_age_seconds: int | None = Field(default=None, ge=0)
    runtime_count: int = Field(ge=1)
    active_runtime_count: int = Field(ge=0)


class AttendanceActivitySummaryResponse(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    revision: str = Field(min_length=32, max_length=32, pattern="^[0-9a-f]+$")
    present_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    exception_count: int = Field(ge=0)
    closeout: AttendanceSummaryCloseout
    coordinator_count: int = Field(default=0, ge=0)
    coordinators_truncated: bool = False
    coordinators: list[AttendanceCoordinatorActivitySummaryResponse] = Field(
        default_factory=list,
        max_length=25,
    )
    last_canonical_update_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class GroupAttendanceSummaryResponse(BaseModel):
    group_id: uuid.UUID
    group_name: str
    revision: str = Field(min_length=32, max_length=32, pattern="^[0-9a-f]+$")
    sessions: list[AttendanceActivitySummaryResponse] = Field(default_factory=list)


class AttendanceMissingPassengerItem(BaseModel):
    passenger_id: uuid.UUID
    display_name: str = Field(min_length=1, max_length=255)


class AttendanceMissingPassengersPageResponse(BaseModel):
    session_id: uuid.UUID
    revision: str = Field(min_length=32, max_length=32, pattern="^[0-9a-f]+$")
    items: list[AttendanceMissingPassengerItem] = Field(default_factory=list)
    has_more: bool
    next_cursor: uuid.UUID | None = None
    page_size: int = Field(ge=1, le=100)
