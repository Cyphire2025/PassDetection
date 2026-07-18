"""
Login Use Case
==============
Orchestrates the user login flow.

Steps:
  1. Look up user by email.
  2. Verify password.
  3. Check account is active.
  4. Record last login timestamp.
  5. Issue access token + refresh token.
  6. Persist refresh token.
  7. Return AuthResponseDTO.
"""

from __future__ import annotations

from app.application.dtos.auth_dtos import AuthResponseDTO, LoginInputDTO, UserOutputDTO
from app.core.logging.logger import get_logger
from app.core.security.jwt import create_access_token, create_refresh_token
from app.core.security.password import verify_password
from app.domain.exceptions.exceptions import AuthenticationError
from app.domain.repositories.interfaces import IUserRepository
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository
from app.infrastructure.security.login_attempt_limiter import LoginAttemptLimiter

logger = get_logger(__name__)


class LoginUseCase:
    """
    Authenticates a user and issues a token pair.

    Depends on:
      - IUserRepository (domain interface — never the ORM directly)
      - RefreshTokenRepository (infrastructure — acceptable here as it
        has no domain logic, only persistence)
    """

    def __init__(
        self,
        user_repository: IUserRepository,
        refresh_token_repository: RefreshTokenRepository,
        login_attempt_limiter: LoginAttemptLimiter | None = None,
    ) -> None:
        self._user_repo  = user_repository
        self._token_repo = refresh_token_repository
        self._limiter = login_attempt_limiter or LoginAttemptLimiter()

    async def execute(
        self,
        dto: LoginInputDTO,
        client_ip: str | None = None,
    ) -> AuthResponseDTO:
        """
        Attempt login with the provided credentials.

        Raises:
            AuthenticationError: If credentials are invalid or account is inactive.
        """
        await self._limiter.check_allowed(email=dto.email, ip_address=client_ip)

        # 1. Fetch user
        user = await self._user_repo.get_by_email(dto.email)
        if not user:
            # Use the same error message to prevent user enumeration
            await self._limiter.record_failure(email=dto.email, ip_address=client_ip)
            raise AuthenticationError("Invalid email or password")

        # 2. Verify password
        if not verify_password(dto.password, user.hashed_password):
            logger.warning("login_failed_bad_password", user_id=str(user.id))
            await self._limiter.record_failure(email=dto.email, ip_address=client_ip)
            raise AuthenticationError("Invalid email or password")

        # 3. Check active
        if not user.is_active:
            logger.warning("login_failed_inactive", user_id=str(user.id))
            await self._limiter.record_failure(email=dto.email, ip_address=client_ip)
            raise AuthenticationError("Your account has been deactivated")

        await self._limiter.record_success(email=dto.email, ip_address=client_ip)

        # 4. Record login
        user.record_login()
        await self._user_repo.update(user)

        # 5. Issue tokens
        access_token, access_expires = create_access_token(
            user_id=user.id,
            role=user.role.value,
            agency_id=user.agency_id,
        )
        refresh_token, refresh_expires = create_refresh_token()

        # 6. Persist refresh token
        await self._token_repo.save(
            token=refresh_token,
            user_id=user.id,
            expires_at=refresh_expires,
            created_from_ip=client_ip,
        )

        logger.info("login_success", user_id=str(user.id), role=user.role.value)

        # 7. Return response DTO
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
            refresh_token=refresh_token,
            access_token_expires_at=access_expires,
        )
