"""Shared revocation boundary for staff-backed mobile principals."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.gc_mobile_models import (
    MobileDeviceSessionModel,
    MobileRefreshTokenModel,
)


async def revoke_user_mobile_sessions(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    user_id: uuid.UUID,
    reason: str,
    subject_role: str | None = None,
    now: datetime | None = None,
) -> None:
    """Fence access JWTs and revoke refresh families for one mobile user.

    Mobile access JWTs embed ``session_generation``. Updating the device row
    therefore invalidates already-issued access tokens, while revoking every
    active refresh row prevents a stale family from creating a replacement.
    """

    revoked_at = now or datetime.now(tz=UTC)
    session_filters = [
        MobileDeviceSessionModel.agency_id == agency_id,
        MobileDeviceSessionModel.user_id == user_id,
        MobileDeviceSessionModel.status == "active",
    ]
    if subject_role is not None:
        session_filters.append(MobileDeviceSessionModel.subject_role == subject_role)
    session_ids = select(MobileDeviceSessionModel.id).where(*session_filters)
    await session.execute(
        update(MobileRefreshTokenModel)
        .where(
            MobileRefreshTokenModel.agency_id == agency_id,
            MobileRefreshTokenModel.session_id.in_(session_ids),
            MobileRefreshTokenModel.revoked_at.is_(None),
        )
        .values(revoked_at=revoked_at, revoke_reason=reason)
    )
    await session.execute(
        update(MobileDeviceSessionModel)
        .where(*session_filters)
        .values(
            status="revoked",
            session_generation=MobileDeviceSessionModel.session_generation + 1,
            revoked_at=revoked_at,
            revoke_reason=reason,
            updated_at=revoked_at,
        )
    )


__all__ = ["revoke_user_mobile_sessions"]
