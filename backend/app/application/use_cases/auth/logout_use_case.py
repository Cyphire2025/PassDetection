"""
Logout Use Case
===============
Revokes the durable session family and all its access/refresh credentials.
"""

from __future__ import annotations

import uuid

from app.core.logging.logger import get_logger
from app.core.security.jwt import decode_access_token
from app.domain.exceptions.exceptions import AuthenticationError
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository

logger = get_logger(__name__)


class LogoutUseCase:
    """Revokes the provided refresh token."""

    def __init__(self, refresh_token_repository: RefreshTokenRepository) -> None:
        self._token_repo = refresh_token_repository

    async def execute(self, refresh_token: str | None = None, access_token: str | None = None) -> None:
        if refresh_token:
            await self._token_repo.revoke(refresh_token)
        if access_token:
            try:
                claims = decode_access_token(access_token)
                session_id, user_id = uuid.UUID(claims["sid"]), uuid.UUID(claims["sub"])
            except (AuthenticationError, KeyError, TypeError, ValueError):
                pass  # Idempotent logout for invalid or expired credentials.
            else:
                await self._token_repo.revoke_session(session_id, user_id=user_id)
        logger.info("logout_success")
