"""Persistence boundary for workforce invitations, MFA, and session fencing."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.identity_security import hash_identity_value, hash_recovery_code
from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import (
    DashboardAuthChallengeModel,
    IdentityActionTokenModel,
    MFARecoveryCodeModel,
    UserModel,
    UserSecurityStateModel,
)

DASHBOARD_MFA_ROLES = frozenset(
    {
        UserRole.SUPER_ADMIN.value,
        UserRole.AGENCY_ADMIN.value,
        UserRole.AGENCY_MANAGER.value,
        UserRole.AGENCY_STAFF.value,
    }
)


def role_requires_dashboard_mfa(role: str | UserRole) -> bool:
    value = role.value if isinstance(role, UserRole) else role
    return value in DASHBOARD_MFA_ROLES


def _as_utc(value: datetime) -> datetime:
    """Normalize timestamps returned by SQLite while preserving PostgreSQL UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class IdentitySecurityRepository:
    """Own every durable transition of workforce security state."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_state(
        self,
        user_id: uuid.UUID,
        *,
        lock: bool = False,
    ) -> UserSecurityStateModel | None:
        statement = select(UserSecurityStateModel).where(
            UserSecurityStateModel.user_id == user_id
        )
        if lock:
            statement = statement.with_for_update()
        return (await self._session.execute(statement)).scalar_one_or_none()

    async def ensure_state(
        self,
        user: UserModel,
        *,
        credential_state: str = "active",
    ) -> UserSecurityStateModel:
        state = await self.get_state(user.id)
        if state is not None:
            return state
        state = UserSecurityStateModel(
            user_id=user.id,
            credential_state=credential_state,
            session_version=1,
            password_changed_at=user.updated_at,
            mfa_required=role_requires_dashboard_mfa(user.role),
        )
        self._session.add(state)
        await self._session.flush()
        return state

    async def issue_action_token(
        self,
        *,
        user_id: uuid.UUID,
        purpose: str,
        expires_in: timedelta,
        created_by_user_id: uuid.UUID | None = None,
        request_ip_hash: str | None = None,
        now: datetime | None = None,
    ) -> tuple[IdentityActionTokenModel, str]:
        active_now = now or datetime.now(tz=UTC)
        active_tokens = (
            await self._session.execute(
                select(IdentityActionTokenModel)
                .where(
                    IdentityActionTokenModel.user_id == user_id,
                    IdentityActionTokenModel.purpose == purpose,
                    IdentityActionTokenModel.consumed_at.is_(None),
                    IdentityActionTokenModel.invalidated_at.is_(None),
                )
                .with_for_update()
            )
        ).scalars().all()
        for active_token in active_tokens:
            active_token.invalidated_at = active_now
        if active_tokens:
            # Flush the invalidation before inserting the replacement so the
            # active-token partial unique index remains a fail-closed race gate.
            await self._session.flush()
        raw_token = secrets.token_urlsafe(32)
        row = IdentityActionTokenModel(
            id=uuid.uuid4(),
            user_id=user_id,
            purpose=purpose,
            token_hash=hash_identity_value(raw_token, purpose=f"action-{purpose}"),
            expires_at=active_now + expires_in,
            created_by_user_id=created_by_user_id,
            request_ip_hash=request_ip_hash,
            created_at=active_now,
        )
        self._session.add(row)
        await self._session.flush()
        return row, raw_token

    async def get_valid_action_token(
        self,
        *,
        raw_token: str,
        purpose: str,
        now: datetime | None = None,
    ) -> IdentityActionTokenModel | None:
        active_now = now or datetime.now(tz=UTC)
        token_hash = hash_identity_value(raw_token, purpose=f"action-{purpose}")
        return (
            await self._session.execute(
                select(IdentityActionTokenModel)
                .where(
                    IdentityActionTokenModel.token_hash == token_hash,
                    IdentityActionTokenModel.purpose == purpose,
                    IdentityActionTokenModel.expires_at > active_now,
                    IdentityActionTokenModel.consumed_at.is_(None),
                    IdentityActionTokenModel.invalidated_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def issue_auth_challenge(
        self,
        *,
        user_id: uuid.UUID,
        purpose: str,
        pending_secret_ciphertext: str | None,
        request_ip_hash: str | None,
        user_agent_hash: str | None,
        now: datetime | None = None,
    ) -> tuple[DashboardAuthChallengeModel, str]:
        active_now = now or datetime.now(tz=UTC)
        await self._session.execute(
            update(DashboardAuthChallengeModel)
            .where(
                DashboardAuthChallengeModel.user_id == user_id,
                DashboardAuthChallengeModel.status == "pending",
            )
            .values(status="cancelled", updated_at=active_now)
        )
        raw_token = secrets.token_urlsafe(32)
        challenge = DashboardAuthChallengeModel(
            id=uuid.uuid4(),
            user_id=user_id,
            purpose=purpose,
            challenge_token_hash=hash_identity_value(
                raw_token,
                purpose="dashboard-auth-challenge",
            ),
            pending_secret_ciphertext=pending_secret_ciphertext,
            status="pending",
            attempt_count=0,
            max_attempts=5,
            expires_at=active_now + timedelta(minutes=5),
            request_ip_hash=request_ip_hash,
            user_agent_hash=user_agent_hash,
            created_at=active_now,
            updated_at=active_now,
        )
        self._session.add(challenge)
        await self._session.flush()
        return challenge, raw_token

    async def get_pending_auth_challenge(
        self,
        *,
        raw_token: str,
        now: datetime | None = None,
    ) -> DashboardAuthChallengeModel | None:
        active_now = now or datetime.now(tz=UTC)
        token_hash = hash_identity_value(raw_token, purpose="dashboard-auth-challenge")
        challenge = (
            await self._session.execute(
                select(DashboardAuthChallengeModel)
                .where(
                    DashboardAuthChallengeModel.challenge_token_hash == token_hash,
                    DashboardAuthChallengeModel.status == "pending",
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
        if challenge is not None and _as_utc(challenge.expires_at) <= _as_utc(active_now):
            challenge.status = "expired"
            challenge.updated_at = active_now
            return None
        return challenge

    async def replace_recovery_codes(
        self,
        *,
        user_id: uuid.UUID,
        raw_codes: list[str],
        now: datetime | None = None,
    ) -> None:
        active_now = now or datetime.now(tz=UTC)
        await self._session.execute(
            delete(MFARecoveryCodeModel).where(MFARecoveryCodeModel.user_id == user_id)
        )
        for code in raw_codes:
            self._session.add(
                MFARecoveryCodeModel(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    code_hash=hash_recovery_code(code, user_id=user_id),
                    created_at=active_now,
                )
            )
        await self._session.flush()

    async def consume_recovery_code(
        self,
        *,
        user_id: uuid.UUID,
        raw_code: str,
        now: datetime | None = None,
    ) -> bool:
        active_now = now or datetime.now(tz=UTC)
        try:
            code_hash = hash_recovery_code(raw_code, user_id=user_id)
        except Exception:
            return False
        result = await self._session.execute(
            update(MFARecoveryCodeModel)
            .where(
                MFARecoveryCodeModel.user_id == user_id,
                MFARecoveryCodeModel.code_hash == code_hash,
                MFARecoveryCodeModel.consumed_at.is_(None),
            )
            .values(consumed_at=active_now)
            .returning(MFARecoveryCodeModel.id)
            .execution_options(synchronize_session=False)
        )
        return result.scalar_one_or_none() is not None

    async def reset_mfa(
        self,
        *,
        state: UserSecurityStateModel,
        now: datetime | None = None,
    ) -> None:
        """Clear every factor artifact and fence all existing bearer sessions.

        The caller must load ``state`` with ``FOR UPDATE`` and revoke refresh
        tokens in the same transaction. A privileged account will be forced
        through fresh enrollment on its next password-authenticated login.
        """

        active_now = now or datetime.now(tz=UTC)
        state.mfa_secret_ciphertext = None
        state.mfa_enabled_at = None
        state.mfa_last_counter = None
        state.session_version += 1
        state.updated_at = active_now
        await self._session.execute(
            delete(MFARecoveryCodeModel).where(
                MFARecoveryCodeModel.user_id == state.user_id
            )
        )
        await self._session.execute(
            update(DashboardAuthChallengeModel)
            .where(
                DashboardAuthChallengeModel.user_id == state.user_id,
                DashboardAuthChallengeModel.status == "pending",
            )
            .values(status="cancelled", updated_at=active_now)
        )
        await self._session.flush()


__all__ = [
    "DASHBOARD_MFA_ROLES",
    "IdentitySecurityRepository",
    "role_requires_dashboard_mfa",
]
