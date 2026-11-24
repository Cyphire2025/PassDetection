"""Read the active account profile for /auth/me."""

from __future__ import annotations

import uuid

from app.application.dtos.auth_dtos import UserOutputDTO, user_output_from_entity
from app.domain.exceptions.exceptions import AuthenticationError
from app.domain.repositories.interfaces import IUserRepository


class GetMeUseCase:
    """Returns the profile of the currently authenticated user."""

    def __init__(self, user_repository: IUserRepository) -> None:
        self._user_repo = user_repository

    async def execute(self, user_id: uuid.UUID) -> UserOutputDTO:
        user = await self._user_repo.get_by_id(user_id)
        if not user or not user.is_active:
            raise AuthenticationError("User not found or deactivated")

        return user_output_from_entity(user)
