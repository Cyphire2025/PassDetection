"""Application-owned immutable attendance read contracts; no persistence imports."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True, slots=True)
class AttendanceCloseoutCoordinatorStatus:
    coordinator_id: uuid.UUID
    coordinator_name: str
    state: Literal["ready", "missing", "stale", "blocked"]
    reported_at: datetime | None
    report_age_seconds: int | None
    pending_count: int
    sending_count: int
    retryable_count: int
    needs_review_count: int
    unreviewed_rejected_count: int
    oldest_pending_age_seconds: int | None
    runtime_id: uuid.UUID | None
    runtime_kind: str
    runtime_status: str


@dataclass(frozen=True, slots=True)
class AttendanceCloseoutStatus:
    ready: bool
    checkpoint_ttl_seconds: int
    active_assignment_count: int
    ready_assignment_count: int
    missing_assignment_count: int
    stale_assignment_count: int
    nonzero_assignment_count: int
    blocked_assignment_count: int
    unresolved_count: int
    oldest_pending_age_seconds: int | None
    coordinators: tuple[AttendanceCloseoutCoordinatorStatus, ...]


# Keep published named-import/pickle identities while defining every class once.
AttendanceCloseoutCoordinatorStatus.__module__ = (
    "app.infrastructure.repositories.attendance_closeout_types"
)
AttendanceCloseoutStatus.__module__ = "app.infrastructure.repositories.attendance_closeout_types"
