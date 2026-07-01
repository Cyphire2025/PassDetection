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

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.jwt import hash_refresh_token
from app.core.logging.logger import get_logger
from app.infrastructure.database.models import RefreshTokenModel

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
    ) -> RefreshTokenModel:
        """Persist a newly issued refresh token."""
        model = RefreshTokenModel(
            token=hash_refresh_token(token),
            user_id=user_id,
            expires_at=expires_at,
            is_revoked=False,
            created_from_ip=created_from_ip,
        )
        self._session.add(model)
        await self._session.flush()
        logger.info("refresh_token_created", user_id=str(user_id))
        return model

    async def get_valid_token(self, token: str) -> RefreshTokenModel | None:
        """
        Retrieve a refresh token that is:
          - Not revoked
          - Not expired
        """
        now = datetime.now(tz=timezone.utc)
        hashed = hash_refresh_token(token)
        result = await self._session.execute(
            select(RefreshTokenModel).where(
                RefreshTokenModel.token.in_([hashed, token]),
                RefreshTokenModel.is_revoked.is_(False),
                RefreshTokenModel.expires_at > now,
            )
        )
        return result.scalar_one_or_none()

    async def revoke(self, token: str) -> None:
        """Revoke a single refresh token (logout from one device)."""
        hashed = hash_refresh_token(token)
        await self._session.execute(
            update(RefreshTokenModel)
            .where(RefreshTokenModel.token.in_([hashed, token]))
            .values(is_revoked=True, revoked_at=datetime.now(tz=timezone.utc))
        )
        await self._session.flush()
        logger.info("refresh_token_revoked")

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> None:
        """Revoke all refresh tokens for a user (force logout all devices)."""
        now = datetime.now(tz=timezone.utc)
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
