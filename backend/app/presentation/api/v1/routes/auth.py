"""
Auth Routes — /api/v1/auth
==========================
HTTP endpoints for authentication.

All business logic lives in use cases — routes only:
  1. Parse the request
  2. Build the use case input DTO
  3. Call the use case
  4. Serialize the output DTO to a response schema
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.auth_dtos import LoginInputDTO, RefreshTokenInputDTO
from app.application.use_cases.auth.get_me_use_case import GetMeUseCase
from app.application.use_cases.auth.login_use_case import LoginUseCase
from app.application.use_cases.auth.logout_use_case import LogoutUseCase
from app.application.use_cases.auth.refresh_token_use_case import RefreshTokenUseCase
from app.domain.entities.entities import User
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.schemas.auth_schemas import (
    AuthResponse,
    LogoutRequest,
    RefreshTokenRequest,
    UserResponse,
)
from app.presentation.dependencies.auth import get_current_active_user

router = APIRouter()



# ── Dependency Factories ──────────────────────────────────────────────────────

def _get_login_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> LoginUseCase:
    return LoginUseCase(
        user_repository=UserRepository(session),
        refresh_token_repository=RefreshTokenRepository(session),
    )


def _get_refresh_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> RefreshTokenUseCase:
    return RefreshTokenUseCase(
        user_repository=UserRepository(session),
        refresh_token_repository=RefreshTokenRepository(session),
    )


def _get_logout_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> LogoutUseCase:
    return LogoutUseCase(
        refresh_token_repository=RefreshTokenRepository(session),
    )


def _get_me_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> GetMeUseCase:
    return GetMeUseCase(
        user_repository=UserRepository(session),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post(
    "/login",
    response_model=AuthResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate with email and password",
    description=(
        "Supports both JSON body and OAuth2 form data (application/x-www-form-urlencoded). "
        "Returns access + refresh tokens."
    ),
)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    use_case: LoginUseCase = Depends(_get_login_use_case),
) -> AuthResponse:
    """
    OAuth2 Password Flow login.

    Accepts standard OAuth2 form data (username = email, password).
    The frontend sends `application/x-www-form-urlencoded`.
    """
    client_ip = request.client.host if request.client else None
    result = await use_case.execute(
        dto=LoginInputDTO(email=form_data.username, password=form_data.password),
        client_ip=client_ip,
    )
    return AuthResponse(
        user=UserResponse.model_validate(result.user.__dict__),
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        token_type=result.token_type,
        access_token_expires_at=result.access_token_expires_at,
    )


@router.post(
    "/refresh",
    response_model=AuthResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh access token",
)
async def refresh_token(
    request: Request,
    body: RefreshTokenRequest,
    use_case: RefreshTokenUseCase = Depends(_get_refresh_use_case),
) -> AuthResponse:
    client_ip = request.client.host if request.client else None
    result = await use_case.execute(
        dto=RefreshTokenInputDTO(refresh_token=body.refresh_token),
        client_ip=client_ip,
    )
    return AuthResponse(
        user=UserResponse.model_validate(result.user.__dict__),
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        token_type=result.token_type,
        access_token_expires_at=result.access_token_expires_at,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Invalidate refresh token",
)
async def logout(
    body: LogoutRequest,
    use_case: LogoutUseCase = Depends(_get_logout_use_case),
    _current_user: User = Depends(get_current_active_user),
) -> Response:
    await use_case.execute(refresh_token=body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)



@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current user profile",
)
async def get_me(
    current_user: User = Depends(get_current_active_user),
    use_case: GetMeUseCase = Depends(_get_me_use_case),
) -> UserResponse:
    result = await use_case.execute(user_id=current_user.id)
    return UserResponse.model_validate(result.__dict__)
