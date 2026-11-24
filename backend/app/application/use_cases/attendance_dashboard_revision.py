"""Canonical activity lookup and stable optimistic attendance revisions."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from app.application.attendance_read_contracts import (
    AttendanceActivityAggregate,
    AttendanceGroupAggregate,
)
from app.application.use_cases.attendance_dashboard_types import AttendanceActivityNotFoundError


def _find_activity(
    group: AttendanceGroupAggregate,
    session_id: uuid.UUID,
) -> AttendanceActivityAggregate:
    activity = next(
        (item for item in group.activities if item.session_id == session_id),
        None,
    )
    if activity is None:
        raise AttendanceActivityNotFoundError
    return activity


def _activity_revision(
    group: AttendanceGroupAggregate,
    activity: AttendanceActivityAggregate,
) -> str:
    return _opaque_revision(
        activity.session_id,
        activity.status,
        activity.updated_at,
        activity.present_count,
        activity.record_count,
        activity.latest_record_created_at,
        group.roster.passenger_count,
        group.roster.latest_updated_at,
        group.roster.latest_passenger_key,
    )


def _opaque_revision(*parts: object) -> str:
    normalized = "|".join(_revision_part(part) for part in parts)
    return hashlib.blake2b(normalized.encode("utf-8"), digest_size=16).hexdigest()


def _revision_part(value: object) -> str:
    if isinstance(value, datetime):
        return _utc(value).isoformat()
    if value is None:
        return "-"
    return str(value)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
