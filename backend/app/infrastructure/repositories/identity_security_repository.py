"""Persistence boundary for workforce invitations, MFA, and session fencing."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.identity_security import (
    active_identity_action_key_id,
    hash_identity_action_token,
    hash_identity_value,
    hash_recovery_code,
    identity_action_token_hash_candidates,
)
from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import (
    DashboardAuthChallengeModel,
    IdentityActionTokenModel,
    IdentityNotificationOutboxModel,
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
        statement = select(UserSecurityStateModel).where(UserSecurityStateModel.user_id == user_id)
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
        # Serialize issuance on the durable account row before inspecting the
        # partial-unique active-token set.  Locking only existing token rows is
        # insufficient when two first-time requests both observe an empty set.
        await self._session.flush()
        user_exists = (
            await self._session.execute(
                select(UserModel.id).where(UserModel.id == user_id).with_for_update()
            )
        ).scalar_one_or_none()
        if user_exists is None:
            raise ValueError("Cannot issue an identity action for a missing account")
        active_tokens = (
            (
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
            )
            .scalars()
            .all()
        )
        for active_token in active_tokens:
            active_token.invalidated_at = active_now
        if active_tokens:
            # Flush the invalidation before inserting the replacement so the
            # active-token partial unique index remains a fail-closed race gate.
            await self._session.flush()
            # A superseded one-time credential must not remain queued for
            # delivery after it can no longer be redeemed.  A worker that was
            # already past its external provider boundary may still deliver an
            # unusable link (at-least-once delivery), but its durable row can no
            # longer be reclaimed or reported as current.
            await self._session.execute(
                update(IdentityNotificationOutboxModel)
                .where(
                    IdentityNotificationOutboxModel.action_token_id.in_(
                        [token.id for token in active_tokens]
                    ),
                    IdentityNotificationOutboxModel.status.in_(("pending", "running")),
                )
                .values(
                    status="dead_letter",
                    lease_expires_at=None,
                    last_error_code="superseded",
                    updated_at=active_now,
                )
            )
        raw_token = secrets.token_urlsafe(32)
        row = IdentityActionTokenModel(
            id=uuid.uuid4(),
            user_id=user_id,
            purpose=purpose,
            token_key_id=active_identity_action_key_id(),
            token_hash=hash_identity_action_token(raw_token, purpose=purpose),
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
        candidates = identity_action_token_hash_candidates(
            raw_token,
            purpose=purpose,
        )
        key_predicates = tuple(
            and_(
                IdentityActionTokenModel.token_key_id == key_id,
                IdentityActionTokenModel.token_hash == token_hash,
            )
            for key_id, token_hash in candidates
        )
        if not key_predicates:
            return None
        return (
            await self._session.execute(
                select(IdentityActionTokenModel)
                .where(
                    IdentityActionTokenModel.purpose == purpose,
                    IdentityActionTokenModel.expires_at > active_now,
                    IdentityActionTokenModel.consumed_at.is_(None),
                    IdentityActionTokenModel.invalidated_at.is_(None),
                    or_(*key_predicates),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def consume_action_token(
        self,
        *,
        token_id: uuid.UUID,
        purpose: str,
        now: datetime | None = None,
    ) -> bool:
        """Atomically consume one still-valid action token.

        ``get_valid_action_token`` already locks the PostgreSQL row, but the
        validity predicates belong in the final mutation as a second boundary.
        This protects alternate database/test runtimes that do not implement
        ``FOR UPDATE`` and makes concurrent redemption correctness explicit.
        """

        active_now = now or datetime.now(tz=UTC)
        result = await self._session.execute(
            update(IdentityActionTokenModel)
            .where(
                IdentityActionTokenModel.id == token_id,
                IdentityActionTokenModel.purpose == purpose,
                IdentityActionTokenModel.expires_at > active_now,
                IdentityActionTokenModel.consumed_at.is_(None),
                IdentityActionTokenModel.invalidated_at.is_(None),
            )
            .values(consumed_at=active_now)
            .returning(IdentityActionTokenModel.id)
            .execution_options(synchronize_session=False)
        )
        return result.scalar_one_or_none() is not None

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
            delete(MFARecoveryCodeModel).where(MFARecoveryCodeModel.user_id == state.user_id)
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
