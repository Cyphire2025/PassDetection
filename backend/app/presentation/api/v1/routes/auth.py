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
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.auth_dtos import LoginInputDTO, RefreshTokenInputDTO
from app.application.use_cases.auth.get_me_use_case import GetMeUseCase
from app.application.use_cases.auth.login_use_case import LoginUseCase
from app.application.use_cases.auth.logout_all_use_case import LogoutAllUseCase
from app.application.use_cases.auth.logout_use_case import LogoutUseCase
from app.application.use_cases.auth.refresh_token_use_case import RefreshTokenUseCase
from app.core.config.settings import get_settings
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import AuthenticationError
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
from app.presentation.dependencies.csrf import (
    require_cookie_csrf,
    require_trusted_request_origin,
)
from app.presentation.security.auth_cookies import clear_auth_cookies, set_auth_cookies
from app.presentation.security.client_ip import trusted_client_ip

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


def _get_logout_all_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> LogoutAllUseCase:
    return LogoutAllUseCase(
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
    response: Response,
    _trusted_origin: None = Depends(require_trusted_request_origin),
    form_data: OAuth2PasswordRequestForm = Depends(),
    use_case: LoginUseCase = Depends(_get_login_use_case),
) -> AuthResponse | Response:
    """
    OAuth2 Password Flow login.

    Accepts standard OAuth2 form data (username = email, password).
    The frontend sends `application/x-www-form-urlencoded`.
    """
    client_ip = trusted_client_ip(request)
    result = await use_case.execute(
        dto=LoginInputDTO(email=form_data.username, password=form_data.password),
        client_ip=client_ip,
    )
    set_auth_cookies(response, access_token=result.access_token, refresh_token=result.refresh_token)
    return AuthResponse(
        user=_user_response(result.user),
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
    response: Response,
    _cookie_csrf: None = Depends(require_cookie_csrf),
    body: RefreshTokenRequest | None = None,
    use_case: RefreshTokenUseCase = Depends(_get_refresh_use_case),
) -> AuthResponse | Response:
    client_ip = trusted_client_ip(request)
    refresh_cookie = request.cookies.get(get_settings().jwt.refresh_cookie_name)
    refresh_value = body.refresh_token if body and body.refresh_token else refresh_cookie
    if not refresh_value:
        error_response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error": {
                    "code": "AUTHENTICATION_ERROR",
                    "message": "Refresh token missing",
                }
            },
        )
        clear_auth_cookies(error_response)
        return error_response
    try:
        result = await use_case.execute(
            dto=RefreshTokenInputDTO(refresh_token=refresh_value),
            client_ip=client_ip,
        )
    except AuthenticationError as exc:
        error_response = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"error": {"code": exc.code, "message": exc.message}},
        )
        clear_auth_cookies(error_response)
        return error_response
    set_auth_cookies(response, access_token=result.access_token, refresh_token=result.refresh_token)
    return AuthResponse(
        user=_user_response(result.user),
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
    request: Request,
    response: Response,
    _cookie_csrf: None = Depends(require_cookie_csrf),
    body: LogoutRequest | None = None,
    use_case: LogoutUseCase = Depends(_get_logout_use_case),
) -> Response:
    refresh_cookie = request.cookies.get(get_settings().jwt.refresh_cookie_name)
    refresh_value = body.refresh_token if body and body.refresh_token else refresh_cookie
    if refresh_value:
        await use_case.execute(refresh_token=refresh_value)
    clear_auth_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Invalidate all refresh sessions for the current user",
)
async def logout_all(
    response: Response,
    current_user: User = Depends(get_current_active_user),
    use_case: LogoutAllUseCase = Depends(_get_logout_all_use_case),
) -> Response:
    await use_case.execute(current_user.id)
    clear_auth_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


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
    return _user_response(result)


def _user_response(user: object) -> UserResponse:
    """Attach server-authoritative dashboard capabilities to auth responses."""

    values = dict(vars(user))
    raw_role = values.get("role")
    role = raw_role.value if isinstance(raw_role, UserRole) else raw_role
    is_active = values.get("is_active") is True
    agency_id = values.get("agency_id")
    can_manage_gc_app = is_active and (
        role == UserRole.SUPER_ADMIN.value
        or (
            role
            in {
                UserRole.AGENCY_ADMIN.value,
                UserRole.AGENCY_MANAGER.value,
            }
            and agency_id is not None
        )
    )
    values["capabilities"] = ["gc_app.manage"] if can_manage_gc_app else []
    return UserResponse.model_validate(values)
