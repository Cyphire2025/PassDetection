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
from app.domain.entities.entities import UserRole
from app.domain.exceptions.exceptions import AuthenticationError, TokenExpiredError
from app.domain.repositories.interfaces import IUserRepository
from app.infrastructure.repositories.identity_security_repository import (
    IdentitySecurityRepository,
    role_requires_dashboard_mfa,
)
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository

logger = get_logger(__name__)


class RefreshTokenUseCase:
    """Validates a refresh token and issues a new token pair."""

    def __init__(
        self,
        user_repository: IUserRepository,
        refresh_token_repository: RefreshTokenRepository,
        identity_security_repository: IdentitySecurityRepository | None = None,
    ) -> None:
        self._user_repo  = user_repository
        self._token_repo = refresh_token_repository
        self._identity_security_repo = identity_security_repository

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
        if user.role == UserRole.CLIENT_MANAGER:
            # Burn any legacy dashboard refresh token issued before this role
            # boundary existed so it cannot be retried indefinitely.
            await self._token_repo.revoke(dto.refresh_token)
            raise AuthenticationError("This account cannot access the dashboard")

        # Migration 0084 backfills existing refresh rows with generation 1 and
        # password-only authentication metadata. Keep the use case compatible
        # with those legacy rows during a rolling deployment as well as with
        # lightweight repository adapters that omit the new attributes.
        session_version = int(getattr(stored_token, "session_version", 1) or 1)
        stored_methods = getattr(stored_token, "authentication_methods", "pwd") or "pwd"
        authentication_methods = tuple(
            method.strip() for method in str(stored_methods).split(",") if method.strip()
        ) or ("pwd",)
        mfa_authenticated_at = getattr(stored_token, "mfa_authenticated_at", None)

        if role_requires_dashboard_mfa(user.role) and (
            mfa_authenticated_at is None
            or not any(
                method in {"totp", "recovery_code"}
                for method in authentication_methods
            )
        ):
            # Pre-MFA refresh rows are deliberately not grandfathered. This
            # closes the rolling-deployment path where a privileged principal
            # could otherwise bypass the new login challenge until expiry.
            await self._token_repo.revoke(dto.refresh_token)
            raise AuthenticationError("MFA sign-in is required")

        if self._identity_security_repo is not None:
            security_state = await self._identity_security_repo.get_state(user.id)
            if (
                security_state is None
                or security_state.credential_state != "active"
                or security_state.session_version != session_version
            ):
                await self._token_repo.revoke(dto.refresh_token)
                raise AuthenticationError("Session is no longer valid")

        # 3. Atomically claim the used refresh token. A concurrent request may
        # have consumed it after the initial lookup while the user was loaded.
        consumed_token = await self._token_repo.consume_valid_token(dto.refresh_token)
        if not consumed_token:
            logger.warning("refresh_token_already_consumed")
            raise TokenExpiredError()

        # 4. Issue new token pair
        access_token, access_expires = create_access_token(
            user_id=user.id,
            role=user.role.value,
            agency_id=user.agency_id,
            session_version=session_version,
            authentication_methods=authentication_methods,
            mfa_authenticated_at=mfa_authenticated_at,
        )
        new_refresh_token, refresh_expires = create_refresh_token()

        # 5. Persist new refresh token
        await self._token_repo.save(
            token=new_refresh_token,
            user_id=user.id,
            expires_at=refresh_expires,
            created_from_ip=client_ip,
            session_version=session_version,
            authentication_methods=authentication_methods,
            mfa_authenticated_at=mfa_authenticated_at,
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
                credential_state=user.credential_state,
                mfa_required=user.mfa_required,
                mfa_enabled=user.mfa_enabled,
            ),
            access_token=access_token,
            refresh_token=new_refresh_token,
            access_token_expires_at=access_expires,
        )
