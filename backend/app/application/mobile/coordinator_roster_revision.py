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

from sqlalchemy import func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.attendance_qr_evidence import (
    attendance_qr_evidence_epoch,
)
from app.infrastructure.database.models import (
    AttendanceRecordModel,
    PassengerQRTokenModel,
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
        select(
            func.count(PassportSubmissionModel.id).label("passenger_count"),
            func.max(PassportSubmissionModel.updated_at).label("passenger_updated_at"),
        )
        .where(
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
        )
        .subquery("coordinator_passenger_state")
    )
    room_state = (
        select(
            func.count(RoomingAssignmentModel.id).label("room_assignment_count"),
            func.max(RoomingAssignmentModel.assigned_at).label("room_assigned_at"),
            func.max(RoomingRoomModel.updated_at).label("room_updated_at"),
            func.max(RoomingHotelModel.updated_at).label("hotel_updated_at"),
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
        .subquery("coordinator_room_state")
    )
    attendance_state = (
        select(
            func.count(AttendanceRecordModel.id).label("attendance_count"),
            func.max(AttendanceRecordModel.created_at).label("attendance_created_at"),
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
        .subquery("coordinator_attendance_state")
    )
    qr_state = (
        select(
            func.count(PassengerQRTokenModel.id).label("qr_count"),
            func.max(PassengerQRTokenModel.token_version).label("qr_version"),
            func.max(PassengerQRTokenModel.updated_at).label("qr_updated_at"),
        )
        .join(
            PassportSubmissionModel,
            PassportSubmissionModel.id == PassengerQRTokenModel.passenger_id,
        )
        .where(
            PassengerQRTokenModel.agency_id == agency_id,
            PassportSubmissionModel.agency_id == agency_id,
            PassportSubmissionModel.group_id == group_id,
        )
        .subquery("coordinator_qr_state")
    )
    state = (
        await session.execute(
            select(
                *passenger_state.c,
                *room_state.c,
                *attendance_state.c,
                *qr_state.c,
            )
            .select_from(passenger_state)
            .join(room_state, true())
            .join(attendance_state, true())
            .join(qr_state, true())
        )
    ).one()
    # The bounded QR evidence lease must renew even when no database row
    # changes.  Including its UTC lease epoch makes an online device perform a
    # fenced full roster refresh before the cached evidence can age out.
    return _state_revision(*state, attendance_qr_evidence_epoch())


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
