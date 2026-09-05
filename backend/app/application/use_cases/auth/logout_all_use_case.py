"""Force logout for all sessions belonging to one user."""

from __future__ import annotations

import uuid

from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository


class LogoutAllUseCase:
    def __init__(
        self,
        refresh_token_repository: RefreshTokenRepository,
        identity_security_repository: IdentitySecurityRepository,
    ) -> None:
        self._token_repo = refresh_token_repository
        self._identity_repo = identity_security_repository

    async def execute(self, user_id: uuid.UUID) -> None:
        # Both repositories share the request transaction. Generation fencing
        # invalidates access JWTs immediately, including a concurrent refresh.
        await self._identity_repo.fence_sessions(user_id)
        await self._token_repo.revoke_all_for_user(user_id)
