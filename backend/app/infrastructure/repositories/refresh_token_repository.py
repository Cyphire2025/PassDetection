"""
Refresh Token Repository
========================
Manages refresh token persistence.

Responsibilities:
  - Store newly issued tokens.
  - Retrieve by token string for validation.
  - Revoke individual tokens (logout).
  - Revoke all tokens for a user (force logout all devices).
  - Clean up expired tokens.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging.logger import get_logger
from app.core.security.jwt import hash_refresh_token
from app.domain.exceptions.exceptions import AuthenticationError, ConflictError
from app.infrastructure.database.models import DashboardSessionModel, RefreshTokenModel, UserModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.notification_repository import NotificationRepository

logger = get_logger(__name__)


class RefreshTokenRepository:
    """Manages refresh token persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(
        self,
        token: str,
        user_id: uuid.UUID,
        expires_at: datetime,
        created_from_ip: str | None = None,
        *,
        session_version: int = 1,
        authentication_methods: tuple[str, ...] = ("pwd",),
        mfa_authenticated_at: datetime | None = None,
        session_id: uuid.UUID | None = None,
    ) -> RefreshTokenModel:
        """Persist a newly issued refresh token."""
        family: DashboardSessionModel | None
        if session_id is None:
            family = DashboardSessionModel(user_id=user_id, expires_at=expires_at,
                                           session_version=session_version)
            self._session.add(family)
            await self._session.flush()
            session_id = family.id
        else:
            family = await self._lock_family(session_id)
            if family is None or family.user_id != user_id or family.revoked_at is not None:
                raise AuthenticationError("Session is no longer valid")
        model = RefreshTokenModel(
            token=hash_refresh_token(token),
            user_id=user_id,
            expires_at=expires_at,
            is_revoked=False,
            created_from_ip=created_from_ip,
            session_version=session_version,
            authentication_methods=",".join(authentication_methods),
            mfa_authenticated_at=mfa_authenticated_at,
            session_id=session_id,
        )
        self._session.add(model)
        await self._session.flush()
        logger.info("refresh_token_created", user_id=str(user_id))
        return model

    async def _lock_family(self, session_id: uuid.UUID) -> DashboardSessionModel | None:
        result = await self._session.execute(select(DashboardSessionModel).where(
            DashboardSessionModel.id == session_id,
        ).with_for_update().execution_options(populate_existing=True))
        return result.scalar_one_or_none()

    async def _lock_account(self, user_id: uuid.UUID) -> None:
        await self._session.scalar(select(UserModel.id).where(UserModel.id == user_id).with_for_update())

    async def claim_for_rotation(self, token: str) -> RefreshTokenModel | None:
        """Serialize rotation with logout and detect actual consumed-token reuse.

        The initial READ COMMITTED observation is the race boundary. A request
        that saw an unconsumed token before another transaction committed can
        retry using the winner's cookie. A later replay revokes the family.
        No client timestamps, host clocks or post-rotation grace are trusted.
        """
        if re.fullmatch(r"[0-9a-fA-F]{64}", token):
            return None
        row = await self._session.scalar(select(RefreshTokenModel).where(
            RefreshTokenModel.token == hash_refresh_token(token),
            RefreshTokenModel.expires_at > datetime.now(UTC),
        ).execution_options(populate_existing=True))
        if row is None:
            return None
        initially_valid = not row.is_revoked
        # Match identity fencing's lock order (account, then family). Auditing
        # a replay also references the user; reversing this order can deadlock
        # a concurrent logout-all or password reset.
        await self._lock_account(row.user_id)
        family = await self._lock_family(row.session_id)
        if family is None or family.revoked_at is not None:
            return None
        current = await self._session.scalar(select(RefreshTokenModel).where(
            RefreshTokenModel.id == row.id,
        ).execution_options(populate_existing=True))
        if current is None:
            return None
        if current.is_revoked:
            if initially_valid:
                raise ConflictError("Another request refreshed this session. Retry with the current credential.",
                                    code="REFRESH_IN_PROGRESS")
            await self._revoke_family(family, reason="refresh_reuse")
            await self._record_reuse(family)
            error = AuthenticationError("This session ended because a refresh credential was reused. Sign in again.")
            error.code = "REFRESH_TOKEN_REUSED"
            raise error
        return await self.consume_valid_token(token)

    async def _record_reuse(self, family: DashboardSessionModel) -> None:
        user = await self._session.get(UserModel, family.user_id)
        await AuditLogRepository(self._session).record(
            action="auth.refresh_reuse_detected", entity_type="dashboard_session",
            entity_id=str(family.id), user_id=family.user_id,
            agency_id=user.agency_id if user is not None else None,
            result="denied", metadata={"reason": "known_consumed_credential", "session_revoked": True},
        )
        if user is not None and user.agency_id is not None:
            await NotificationRepository(self._session).create(
                agency_id=user.agency_id, user_id=user.id, type="security_session_revoked",
                title="Sign-in session ended", priority="high", category="security",
                message="A previously used sign-in credential was reused. That session was ended. Review your account security if this was unexpected.",
                dedupe_key=f"refresh-reuse:{family.id}",
                entity_type="dashboard_session", entity_id=str(family.id),
            )

    async def _revoke_family(self, family: DashboardSessionModel, *, reason: str) -> None:
        now = datetime.now(UTC)
        family.revoked_at = family.revoked_at or now
        family.revocation_reason = family.revocation_reason or reason
        await self._session.execute(update(RefreshTokenModel).where(
            RefreshTokenModel.session_id == family.id,
            RefreshTokenModel.is_revoked.is_(False),
        ).values(is_revoked=True, revoked_at=now))
        await self._session.flush()

    async def revoke_session(self, session_id: uuid.UUID, *, user_id: uuid.UUID) -> None:
        await self._lock_account(user_id)
        family = await self._lock_family(session_id)
        if family is not None and family.user_id == user_id:
            await self._revoke_family(family, reason="logout")

    async def get_valid_token(self, token: str) -> RefreshTokenModel | None:
        """
        Retrieve a refresh token that is:
          - Not revoked
          - Not expired
        """
        # Database digests must never be reusable bearer credentials.
        if re.fullmatch(r"[0-9a-fA-F]{64}", token):
            return None
        now = datetime.now(tz=UTC)
        hashed = hash_refresh_token(token)
        result = await self._session.execute(
            select(RefreshTokenModel).where(
                RefreshTokenModel.token == hashed,
                RefreshTokenModel.is_revoked.is_(False),
                RefreshTokenModel.expires_at > now,
            )
        )
        return result.scalar_one_or_none()

    async def consume_valid_token(self, token: str) -> RefreshTokenModel | None:
        """Atomically revoke and return one currently valid refresh token.

        The validity predicates are part of the ``UPDATE`` itself. Concurrent
        refresh requests therefore cannot both claim the same token: after the
        first transaction updates the row, later contenders re-check the
        predicates and receive no row from ``RETURNING``.

        Only keyed hashes are readable. Legacy plaintext rows cannot be used
        and are revoked by the release data migration.
        """

        if re.fullmatch(r"[0-9a-fA-F]{64}", token):
            return None
        now = datetime.now(tz=UTC)
        hashed = hash_refresh_token(token)
        result = await self._session.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.token == hashed,
                RefreshTokenModel.is_revoked.is_(False),
                RefreshTokenModel.expires_at > now,
            )
            .values(is_revoked=True, revoked_at=now)
            .returning(RefreshTokenModel)
            .execution_options(synchronize_session=False)
        )
        consumed = result.scalar_one_or_none()
        if consumed is not None:
            logger.info("refresh_token_consumed", user_id=str(consumed.user_id))
        return consumed

    async def revoke(self, token: str) -> None:
        """Revoke the corresponding family, including a racing successor."""
        hashed = hash_refresh_token(token)
        row = await self._session.scalar(select(RefreshTokenModel).where(RefreshTokenModel.token == hashed))
        if row is not None:
            await self.revoke_session(row.session_id, user_id=row.user_id)
        logger.info("refresh_token_revoked")

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        """Revoke all refresh tokens for a user (force logout all devices)."""
        now = datetime.now(tz=UTC)
        await self._session.execute(update(DashboardSessionModel).where(
            DashboardSessionModel.user_id == user_id,
            DashboardSessionModel.revoked_at.is_(None),
        ).values(revoked_at=now, revocation_reason="logout_all"))
        await self._session.execute(
            update(RefreshTokenModel)
            .where(
                RefreshTokenModel.user_id == user_id,
                RefreshTokenModel.is_revoked.is_(False),
            )
            .values(is_revoked=True, revoked_at=now)
        )
        await self._session.flush()
        logger.info("all_refresh_tokens_revoked", user_id=str(user_id))
