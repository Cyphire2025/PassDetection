"""
Logout Use Case
===============
Revokes the user's refresh token, ending their session.
The access token remains valid until its natural expiry —
this is by design (short TTL mitigates the risk).
"""

from __future__ import annotations

from app.core.logging.logger import get_logger
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository

logger = get_logger(__name__)


class LogoutUseCase:
    """Revokes the provided refresh token."""

    def __init__(self, refresh_token_repository: RefreshTokenRepository) -> None:
        self._token_repo = refresh_token_repository

    async def execute(self, refresh_token: str) -> None:
        await self._token_repo.revoke(refresh_token)
        logger.info("logout_success")
