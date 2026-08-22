"""
Get Me Use Case
===============
Returns the currently authenticated user's profile.
Used by the /auth/me endpoint.
"""

from __future__ import annotations

import uuid

from app.application.dtos.auth_dtos import UserOutputDTO
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

        return UserOutputDTO(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role.value,
            agency_id=user.agency_id,
            is_active=user.is_active,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
            updated_at=user.updated_at,
            credential_state=user.credential_state,
            mfa_required=user.mfa_required,
            mfa_enabled=user.mfa_enabled,
        )
