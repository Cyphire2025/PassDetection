"""Resolve an admitted canonical activity while preserving its existing evidence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import AttendanceSessionModel


async def _finish_activity_creation(
    session: AsyncSession,
    attendance_session: AttendanceSessionModel,
    *,
    inserted_id: uuid.UUID | None,
    now: datetime,
    allow_existing_changes: bool,
    scheduled_starts_at: datetime | None,
    scheduled_ends_at: datetime | None,
    schedule_timezone: str | None,
) -> tuple[AttendanceSessionModel, str]:
    """Preserve strict additive resolution while retaining the website lifecycle."""
    if not allow_existing_changes:
        if inserted_id is not None:
            return attendance_session, "created"

        def comparable(value: datetime | None) -> datetime | None:
            if value is None:
                return None
            return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

        actual = (
            comparable(attendance_session.scheduled_starts_at),
            comparable(attendance_session.scheduled_ends_at),
            attendance_session.schedule_timezone,
        )
        expected = (
            comparable(scheduled_starts_at),
            comparable(scheduled_ends_at),
            schedule_timezone,
        )
        if attendance_session.status != "active" or actual != expected:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An existing activity has a different state or schedule; creation cannot change it.",
            )
        return attendance_session, "existing"

    if attendance_session.status == "draft":
        attendance_session.status = "active"
        attendance_session.started_at = attendance_session.started_at or now
        attendance_session.updated_at = now
        _apply_initial_attendance_schedule(
            attendance_session,
            scheduled_starts_at=scheduled_starts_at,
            scheduled_ends_at=scheduled_ends_at,
            schedule_timezone=schedule_timezone,
        )
        await session.flush()
        return attendance_session, "activated_existing"
    schedule_changed = _apply_initial_attendance_schedule(
        attendance_session,
        scheduled_starts_at=scheduled_starts_at,
        scheduled_ends_at=scheduled_ends_at,
        schedule_timezone=schedule_timezone,
    )
    if schedule_changed:
        attendance_session.updated_at = now
        await session.flush()
    return attendance_session, "created" if inserted_id is not None else "existing"


def _apply_initial_attendance_schedule(
    attendance_session: AttendanceSessionModel,
    *,
    scheduled_starts_at: datetime | None,
    scheduled_ends_at: datetime | None,
    schedule_timezone: str | None,
) -> bool:
    if scheduled_starts_at is None:
        return False
    existing = (
        attendance_session.scheduled_starts_at,
        attendance_session.scheduled_ends_at,
        attendance_session.schedule_timezone,
    )
    requested = (scheduled_starts_at, scheduled_ends_at, schedule_timezone)
    if all(value is None for value in existing):
        attendance_session.scheduled_starts_at = scheduled_starts_at
        attendance_session.scheduled_ends_at = scheduled_ends_at
        attendance_session.schedule_timezone = schedule_timezone
        return True
    if existing != requested:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ATTENDANCE_SCHEDULE_CONFLICT",
                "message": "The existing attendance activity has a different schedule.",
            },
        )
    return False
