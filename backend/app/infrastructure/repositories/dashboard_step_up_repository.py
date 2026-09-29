"""Preserve verified step-up assurance within an existing dashboard family."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import get_settings
from app.domain.exceptions.exceptions import AuthenticationError
from app.infrastructure.database.models import (
    DashboardSessionModel,
    RefreshTokenModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass
class LockedStepUpSession:
    family: DashboardSessionModel
    state: UserSecurityStateModel
    credentials: list[RefreshTokenModel]
    deadline: datetime

    def record_assurance(self, *, method: str, now: datetime) -> None:
        """Call only after this transaction verifies and consumes the factor."""
        if method not in {"totp", "recovery_code"}:
            raise ValueError("Unsupported step-up factor")
        self.family.expires_at = self.deadline
        for credential in self.credentials:
            # Freeze the legacy MFA-based expiry cap before changing MFA time.
            # Consumed/revoked rows were never selected and remain untouched.
            credential.expires_at = self.deadline
            credential.authentication_methods = f"pwd,{method}"
            credential.mfa_authenticated_at = now


async def lock_step_up_session(
    session: AsyncSession, *, user_id: uuid.UUID, session_id: uuid.UUID,
    session_version: int, deadline: datetime | None, now: datetime | None = None,
) -> LockedStepUpSession:
    """Use rotation's account → family order before locking factor state.

    The account lock also serializes logout-all/security-generation fencing.
    Re-read all live authority after waiting; a request's earlier dependency
    check cannot authorize a session that was revoked while it waited.
    """
    user = await session.scalar(select(UserModel).where(UserModel.id == user_id)
                                .with_for_update().execution_options(populate_existing=True))
    if user is None or not user.is_active or user.deleted_at is not None:
        raise AuthenticationError("Session is no longer valid")
    active_now = now or datetime.now(UTC)
    family = await session.scalar(select(DashboardSessionModel).where(
        DashboardSessionModel.id == session_id, DashboardSessionModel.user_id == user_id,
        DashboardSessionModel.session_version == session_version,
        DashboardSessionModel.revoked_at.is_(None), DashboardSessionModel.expires_at > active_now,
    ).with_for_update().execution_options(populate_existing=True))
    state = await IdentitySecurityRepository(session).get_state(user_id, lock=True)
    if (family is None or state is None or state.credential_state != "active"
            or state.session_version != session_version or deadline is None):
        raise AuthenticationError("Session is no longer valid")
    credentials = list(await session.scalars(select(RefreshTokenModel).where(
        RefreshTokenModel.session_id == session_id, RefreshTokenModel.user_id == user_id,
        RefreshTokenModel.session_version == session_version,
        RefreshTokenModel.is_revoked.is_(False), RefreshTokenModel.expires_at > active_now,
    ).with_for_update().execution_options(populate_existing=True)))
    if not credentials:
        raise AuthenticationError("Session is no longer valid")
    bounds = [_utc(family.expires_at)]
    for credential in credentials:
        bounds.append(_utc(credential.expires_at))
        if credential.mfa_authenticated_at is not None:
            bounds.append(_utc(credential.mfa_authenticated_at) + timedelta(
                days=get_settings().jwt.refresh_token_expire_days))
    effective_deadline = min(bounds)
    # JWT NumericDate has second precision. Do not change a database deadline's
    # fractional seconds merely because its signed representation was rounded.
    if int(effective_deadline.timestamp()) != int(deadline.timestamp()):
        effective_deadline = min(effective_deadline, _utc(deadline))
    if effective_deadline <= (now or datetime.now(UTC)):
        raise AuthenticationError("Session is no longer valid")
    return LockedStepUpSession(family, state, credentials, effective_deadline)
