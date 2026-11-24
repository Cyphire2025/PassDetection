"""Immutable office-attendance projection and conflict types."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.application.attendance_read_contracts import MissingPassengerPage


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
