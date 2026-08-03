"""Authoritative, compact revision for the coordinator's offline roster.

The revision is deliberately derived from the same tenant/group-scoped source
tables used by the mobile roster projection.  Targeted journal entries store
the revision observed inside their mutation transaction.  A device may apply
those entries without replacing the whole roster only when that revision
matches the manifest; any unjournaled or concurrent change therefore falls
back to the existing full reconciliation path.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    AttendanceRecordModel,
    PassportSubmissionModel,
    RoomingAssignmentModel,
    RoomingHotelModel,
    RoomingRoomModel,
)


async def coordinator_roster_revision(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    group_id: uuid.UUID,
) -> int:
    """Return a JavaScript-safe opaque revision for one authorized roster."""

    passenger_state = (
        await session.execute(
            select(
                func.count(PassportSubmissionModel.id),
                func.max(PassportSubmissionModel.updated_at),
            ).where(
                PassportSubmissionModel.agency_id == agency_id,
                PassportSubmissionModel.group_id == group_id,
            )
        )
    ).one()
    room_state = (
        await session.execute(
            select(
                func.count(RoomingAssignmentModel.id),
                func.max(RoomingAssignmentModel.assigned_at),
                func.max(RoomingRoomModel.updated_at),
                func.max(RoomingHotelModel.updated_at),
            )
            .join(
                RoomingHotelModel,
                RoomingHotelModel.id == RoomingAssignmentModel.hotel_id,
            )
            .join(
                RoomingRoomModel,
                RoomingRoomModel.id == RoomingAssignmentModel.room_id,
            )
            .where(
                RoomingHotelModel.agency_id == agency_id,
                RoomingHotelModel.group_id == group_id,
            )
        )
    ).one()
    attendance_state = (
        await session.execute(
            select(
                func.count(AttendanceRecordModel.id),
                func.max(AttendanceRecordModel.created_at),
            )
            .join(
                PassportSubmissionModel,
                PassportSubmissionModel.id == AttendanceRecordModel.passenger_id,
            )
            .where(
                AttendanceRecordModel.agency_id == agency_id,
                PassportSubmissionModel.agency_id == agency_id,
                PassportSubmissionModel.group_id == group_id,
            )
        )
    ).one()
    return _state_revision(*passenger_state, *room_state, *attendance_state)


def _state_revision(*parts: object) -> int:
    normalized: list[str] = []
    meaningful = False
    for part in parts:
        if isinstance(part, datetime):
            value = part.astimezone(UTC).isoformat()
            meaningful = True
        elif part is None:
            value = "-"
        else:
            value = str(part)
            meaningful = meaningful or value not in {"", "0", "False"}
        normalized.append(value)
    if not meaningful:
        return 0
    digest = hashlib.blake2b("|".join(normalized).encode(), digest_size=8).digest()
    # Mobile contracts use JSON numbers, so never exceed Number.MAX_SAFE_INTEGER.
    revision = int.from_bytes(digest, "big") & ((1 << 53) - 1)
    return revision or 1


__all__ = ["coordinator_roster_revision"]
