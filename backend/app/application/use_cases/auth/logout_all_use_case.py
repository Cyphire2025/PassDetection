"""Force logout for all sessions belonging to one user."""

from __future__ import annotations

import uuid

from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository


class LogoutAllUseCase:
    def __init__(self, refresh_token_repository: RefreshTokenRepository) -> None:
        self._token_repo = refresh_token_repository

    async def execute(self, user_id: uuid.UUID) -> None:
        await self._token_repo.revoke_all_for_user(user_id)
