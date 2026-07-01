"""
Refresh Token Use Case
======================
Rotates an expired access token using a valid refresh token.

Token Rotation Strategy:
  - On every successful refresh, the old refresh token is revoked
    and a NEW refresh token is issued.
  - This means a stolen refresh token can only be used once before
    the real user's next refresh invalidates it.
"""

from __future__ import annotations

from app.application.dtos.auth_dtos import AuthResponseDTO, RefreshTokenInputDTO, UserOutputDTO
from app.core.logging.logger import get_logger
from app.core.security.jwt import create_access_token, create_refresh_token
from app.domain.exceptions.exceptions import AuthenticationError, TokenExpiredError
from app.domain.repositories.interfaces import IUserRepository
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository

logger = get_logger(__name__)


class RefreshTokenUseCase:
    """Validates a refresh token and issues a new token pair."""

    def __init__(
        self,
        user_repository: IUserRepository,
        refresh_token_repository: RefreshTokenRepository,
    ) -> None:
        self._user_repo  = user_repository
        self._token_repo = refresh_token_repository

    async def execute(
        self,
        dto: RefreshTokenInputDTO,
        client_ip: str | None = None,
    ) -> AuthResponseDTO:
        # 1. Look up the refresh token in DB
        stored_token = await self._token_repo.get_valid_token(dto.refresh_token)
        if not stored_token:
            logger.warning("refresh_token_invalid_or_expired")
            raise TokenExpiredError()

        # 2. Load the user
        user = await self._user_repo.get_by_id(stored_token.user_id)
        if not user or not user.is_active:
            raise AuthenticationError("User account not found or deactivated")

        # 3. Revoke the used refresh token (rotation)
        await self._token_repo.revoke(dto.refresh_token)

        # 4. Issue new token pair
        access_token, access_expires = create_access_token(
            user_id=user.id,
            role=user.role.value,
            agency_id=user.agency_id,
        )
        new_refresh_token, refresh_expires = create_refresh_token()

        # 5. Persist new refresh token
        await self._token_repo.save(
            token=new_refresh_token,
            user_id=user.id,
            expires_at=refresh_expires,
            created_from_ip=client_ip,
        )

        logger.info("token_refreshed", user_id=str(user.id))

        return AuthResponseDTO(
            user=UserOutputDTO(
                id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=user.role.value,
                agency_id=user.agency_id,
                is_active=user.is_active,
                last_login_at=user.last_login_at,
                created_at=user.created_at,
                updated_at=user.updated_at,
            ),
            access_token=access_token,
            refresh_token=new_refresh_token,
            access_token_expires_at=access_expires,
        )
