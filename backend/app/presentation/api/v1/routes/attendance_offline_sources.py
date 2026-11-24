"""Bounded tenant-scoped activity and approved-QR source admission."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Protocol, Sequence, cast

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.entities.entities import OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
from app.infrastructure.database.models import (
    AttendanceSessionModel,
    PassengerQRTokenModel,
    PassportSubmissionModel,
)
from app.infrastructure.repositories.operational_roster import operational_roster_member


class OfflinePassengerRow(Protocol):
    id: uuid.UUID
    client_name: str
    token_hash: str
    token_version: int
    expires_at: datetime


async def load_scheduled_offline_activities(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
) -> list[tuple[AttendanceSessionModel, datetime, datetime]]:
    attendance_sessions = list(
        (
            await session.execute(
                select(AttendanceSessionModel)
                .where(
                    AttendanceSessionModel.agency_id == agency_id,
                    AttendanceSessionModel.group_id == group_id,
                    AttendanceSessionModel.id == AttendanceSessionModel.canonical_session_id,
                    AttendanceSessionModel.status == "active",
                )
                .order_by(
                    AttendanceSessionModel.scheduled_starts_at,
                    AttendanceSessionModel.id,
                )
                .limit(201)
            )
        ).scalars()
    )
    if not attendance_sessions:
        raise _offline_readiness_error(
            "OFFLINE_ACTIVITY_NOT_AVAILABLE",
            "No active attendance activity is available for offline scanning.",
        )
    if len(attendance_sessions) > 200:
        raise _offline_readiness_error(
            "OFFLINE_ACTIVITY_LIMIT_EXCEEDED",
            "Too many active attendance activities are configured for offline use.",
        )
    scheduled_sessions: list[tuple[AttendanceSessionModel, datetime, datetime]] = []
    for item in attendance_sessions:
        scheduled_starts_at = item.scheduled_starts_at
        scheduled_ends_at = item.scheduled_ends_at
        if scheduled_starts_at is None or scheduled_ends_at is None:
            raise _offline_readiness_error(
                "ATTENDANCE_SCHEDULE_REQUIRED",
                "Every active attendance activity needs an explicit start and end time.",
            )
        scheduled_sessions.append((item, scheduled_starts_at, scheduled_ends_at))
    return scheduled_sessions


async def approved_offline_passenger_count(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
) -> int:
    approved_count = int(
        await session.scalar(
            select(func.count(PassportSubmissionModel.id)).where(
                PassportSubmissionModel.agency_id == agency_id,
                PassportSubmissionModel.group_id == group_id,
                PassportSubmissionModel.status.in_(OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES),
                operational_roster_member(),
            )
        )
        or 0
    )
    return approved_count


async def load_authorized_offline_passengers(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
    now: datetime,
    approved_count: int,
) -> Sequence[OfflinePassengerRow]:
    passenger_rows = list(
        (
            await session.execute(
                select(
                    PassportSubmissionModel.id,
                    PassportSubmissionModel.client_name,
                    PassengerQRTokenModel.token_hash,
                    PassengerQRTokenModel.token_version,
                    PassengerQRTokenModel.expires_at,
                )
                .join(
                    PassengerQRTokenModel,
                    PassengerQRTokenModel.passenger_id == PassportSubmissionModel.id,
                )
                .where(
                    PassportSubmissionModel.agency_id == agency_id,
                    PassportSubmissionModel.group_id == group_id,
                    PassportSubmissionModel.status.in_(
                        OPERATIONALLY_APPROVED_PASSPORT_STATUS_VALUES
                    ),
                    operational_roster_member(),
                    PassengerQRTokenModel.agency_id == agency_id,
                    PassengerQRTokenModel.is_active.is_(True),
                    PassengerQRTokenModel.revoked_at.is_(None),
                    PassengerQRTokenModel.expires_at > now,
                    func.length(PassengerQRTokenModel.token_hash) == 64,
                )
                .order_by(PassportSubmissionModel.id)
                .limit(2_001)
            )
        ).all()
    )
    if approved_count == 0 or len(passenger_rows) != approved_count:
        raise _offline_readiness_error(
            "OFFLINE_ROSTER_INCOMPLETE",
            "The approved roster does not yet have complete active QR authorization.",
        )
    if len(passenger_rows) > 2_000:
        raise _offline_readiness_error(
            "OFFLINE_ROSTER_LIMIT_EXCEEDED",
            "The roster exceeds the supported offline authorization size.",
        )
    return cast(Sequence[OfflinePassengerRow], passenger_rows)


def _offline_readiness_error(
    code: str,
    message: str,
    *,
    service_unavailable: bool = False,
) -> HTTPException:
    return HTTPException(
        status_code=(
            status.HTTP_503_SERVICE_UNAVAILABLE if service_unavailable else status.HTTP_409_CONFLICT
        ),
        detail={"code": code, "message": message},
        headers={"Cache-Control": "private, no-store", "Retry-After": "30"},
    )
