"""Count-only attendance closeout values and immutable response projections."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal as Literal  # Legacy dataclass annotation resolution.

from app.application.attendance_closeout_read_contracts import (
    AttendanceCloseoutCoordinatorStatus as AttendanceCloseoutCoordinatorStatus,
)
from app.application.attendance_closeout_read_contracts import (
    AttendanceCloseoutStatus as AttendanceCloseoutStatus,
)

ATTENDANCE_CLOSEOUT_CHECKPOINT_TTL_SECONDS = 120


@dataclass(frozen=True, slots=True)
class AttendanceCloseoutCounts:
    pending_count: int
    sending_count: int
    retryable_count: int
    needs_review_count: int
    unreviewed_rejected_count: int
    oldest_pending_age_seconds: int | None

    @property
    def delivery_count(self) -> int:
        return self.pending_count + self.sending_count + self.retryable_count

    @property
    def unresolved_count(self) -> int:
        return self.delivery_count + self.needs_review_count + self.unreviewed_rejected_count


@dataclass(frozen=True, slots=True)
class AttendanceCloseoutAssignmentCheckpoint:
    coordinator_id: uuid.UUID
    coordinator_name: str
    assigned_at: datetime
    reported_at: datetime | None
    counts: AttendanceCloseoutCounts | None
    runtime_id: uuid.UUID | None = None
    runtime_kind: str = "legacy_account"
    runtime_status: str = "active"
