"""Activity lifecycle for tour operations; preserve tenant, lock and transaction boundaries."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.entities.entities import GroupStatus
from app.domain.value_objects.attendance_activity import normalize_attendance_activity_name
from app.infrastructure.database.models import AttendanceSessionModel, ClientGroupModel


async def _canonical_attendance_activity_admission(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    normalized_name: str,
) -> uuid.UUID | None:
    """Serialize canonical activity creation on the tenant-owned group row.

    Returning an existing open canonical UUID makes normalized retries
    idempotent. The group lock and database partial unique index together stop
    concurrent manager requests from admitting two open activities with the
    same normalized name.
    """

    locked_group_id = await session.scalar(
        select(ClientGroupModel.id)
        .where(
            ClientGroupModel.id == group_id,
            ClientGroupModel.agency_id == agency_id,
            ClientGroupModel.status != GroupStatus.DELETED.value,
            ClientGroupModel.deleted_at.is_(None),
        )
        .with_for_update()
    )
    if locked_group_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group was not found")

    existing_id = await session.scalar(
        select(AttendanceSessionModel.id)
        .where(
            AttendanceSessionModel.agency_id == agency_id,
            AttendanceSessionModel.group_id == group_id,
            AttendanceSessionModel.normalized_name == normalized_name,
            AttendanceSessionModel.status.in_(("draft", "active")),
            AttendanceSessionModel.id == AttendanceSessionModel.canonical_session_id,
        )
        .order_by(AttendanceSessionModel.created_at, AttendanceSessionModel.id)
        .limit(1)
    )
    if existing_id is not None:
        return existing_id

    current = int(
        await session.scalar(
            select(func.count(AttendanceSessionModel.id)).where(
                AttendanceSessionModel.agency_id == agency_id,
                AttendanceSessionModel.group_id == group_id,
                AttendanceSessionModel.id == AttendanceSessionModel.canonical_session_id,
            )
        )
        or 0
    )
    maximum = get_settings().mobile.max_attendance_sessions_per_group
    if current >= maximum:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "ATTENDANCE_SESSION_CAPACITY_REACHED",
                "message": (
                    f"This trip supports at most {maximum:,} attendance activities. "
                    "Archive or remove an existing activity before creating another."
                ),
            },
        )
    return None


async def _create_canonical_attendance_activity(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    name: str,
    created_by_user_id: uuid.UUID,
    scheduled_starts_at: datetime | None = None,
    scheduled_ends_at: datetime | None = None,
    schedule_timezone: str | None = None,
) -> tuple[AttendanceSessionModel, str]:
    """Create or resolve one manager-owned stable UUID for an open activity."""

    display_name = " ".join(name.split())
    normalized_name = normalize_attendance_activity_name(display_name)
    existing_id = await _canonical_attendance_activity_admission(
        session,
        agency_id=agency_id,
        group_id=group_id,
        normalized_name=normalized_name,
    )
    now = datetime.now(tz=UTC)
    inserted_id: uuid.UUID | None = None
    if existing_id is None:
        candidate_id = uuid.uuid4()
        inserted_id = (
            await session.execute(
                pg_insert(AttendanceSessionModel)
                .values(
                    id=candidate_id,
                    agency_id=agency_id,
                    group_id=group_id,
                    name=display_name,
                    normalized_name=normalized_name,
                    canonical_session_id=candidate_id,
                    status="active",
                    created_by_user_id=created_by_user_id,
                    created_at=now,
                    updated_at=now,
                    started_at=now,
                    scheduled_starts_at=scheduled_starts_at,
                    scheduled_ends_at=scheduled_ends_at,
                    schedule_timezone=schedule_timezone,
                )
                .on_conflict_do_nothing()
                .returning(AttendanceSessionModel.id)
            )
        ).scalar_one_or_none()

    target_id = inserted_id or existing_id
    lookup = select(AttendanceSessionModel).where(
        AttendanceSessionModel.agency_id == agency_id,
        AttendanceSessionModel.group_id == group_id,
        AttendanceSessionModel.id == AttendanceSessionModel.canonical_session_id,
    )
    if target_id is not None:
        lookup = lookup.where(AttendanceSessionModel.id == target_id)
    else:
        # A mixed-version deployment can still race an older writer that does
        # not take the group lock. Resolve the unique-index winner fail-safely.
        lookup = lookup.where(
            AttendanceSessionModel.normalized_name == normalized_name,
            AttendanceSessionModel.status.in_(("draft", "active")),
        )
    attendance_session = (await session.execute(lookup.limit(1))).scalar_one_or_none()
    if attendance_session is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The shared attendance activity changed while it was being created. Try again.",
        )

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
