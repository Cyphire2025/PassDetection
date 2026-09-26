"""Shared live session check for dashboard HTTP and realtime credentials."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions.exceptions import AuthenticationError
from app.infrastructure.database.dashboard_session_models import DashboardSessionModel


async def require_dashboard_session(session: AsyncSession, claims: dict[str, Any]) -> uuid.UUID:
    try:
        session_id = uuid.UUID(claims["sid"])
        user_id = uuid.UUID(claims["sub"])
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise AuthenticationError("Sign in again to continue") from exc
    valid = await session.scalar(select(DashboardSessionModel.id).where(
        DashboardSessionModel.id == session_id,
        DashboardSessionModel.user_id == user_id,
        DashboardSessionModel.session_version == claims.get("sv"),
        DashboardSessionModel.revoked_at.is_(None),
        DashboardSessionModel.expires_at > datetime.now(UTC),
    ))
    if valid is None:
        raise AuthenticationError("Session is no longer valid")
    return session_id
