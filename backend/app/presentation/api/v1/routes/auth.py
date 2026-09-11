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

from collections.abc import AsyncIterator
from types import SimpleNamespace

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
from app.core.security.jwt import decode_access_token
from app.domain.entities.entities import User
from app.domain.exceptions.exceptions import AuthenticationError
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.auth_access_level import router as access_level_router
from app.presentation.api.v1.routes.auth_identity import (
    begin_dashboard_mfa_challenge,
)
from app.presentation.api.v1.routes.auth_identity import (
    router as identity_router,
)
from app.presentation.api.v1.schemas.auth_schemas import (
    AuthChallengeResponse,
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
from app.presentation.security.access_level import (
    ACCESS_LEVEL_COOKIE,
    access_level_response_values,
    clear_access_level_cookie,
)
from app.presentation.security.auth_cookies import clear_auth_cookies, set_auth_cookies
from app.presentation.security.auth_user_response import user_response as _user_response
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter()
router.include_router(identity_router)
router.include_router(access_level_router)



# ── Dependency Factories ──────────────────────────────────────────────────────

async def _get_login_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> AsyncIterator[LoginUseCase]:
    use_case = LoginUseCase(
        user_repository=UserRepository(session),
        refresh_token_repository=RefreshTokenRepository(session),
    )
    try:
        yield use_case
    finally:
        await use_case.aclose()


def _get_refresh_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> RefreshTokenUseCase:
    return RefreshTokenUseCase(
        user_repository=UserRepository(session),
        refresh_token_repository=RefreshTokenRepository(session),
        identity_security_repository=IdentitySecurityRepository(session),
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
        identity_security_repository=IdentitySecurityRepository(session),
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
    response_model=AuthResponse | AuthChallengeResponse,
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
    session: AsyncSession = Depends(get_db_session),
) -> AuthResponse | AuthChallengeResponse | Response:
    """
    OAuth2 Password Flow login.

    Accepts standard OAuth2 form data (username = email, password).
    The frontend sends `application/x-www-form-urlencoded`.
    """
    client_ip = trusted_client_ip(request)
    user = await use_case.verify_credentials(
        dto=LoginInputDTO(email=form_data.username, password=form_data.password),
        client_ip=client_ip,
    )
    challenge = await begin_dashboard_mfa_challenge(
        user=user,
        request=request,
        session=session,
    )
    if challenge is not None:
        clear_auth_cookies(response)
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return challenge
    security_state = await IdentitySecurityRepository(session).get_state(user.id)
    clear_access_level_cookie(response)
    result = await use_case.issue_session(
        user,
        client_ip=client_ip,
        session_version=security_state.session_version if security_state else 1,
        authentication_methods=("pwd",),
    )
    set_auth_cookies(
        response, access_token=result.access_token, refresh_token=result.refresh_token,
        access_token_expires_at=result.access_token_expires_at,
        refresh_token_expires_at=result.refresh_token_expires_at,
    )
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
    selected_values = access_level_response_values(
        result.user, request.cookies,
        decode_access_token(result.access_token) if request.cookies.get(ACCESS_LEVEL_COOKIE) else {},
    )
    set_auth_cookies(
        response, access_token=result.access_token, refresh_token=result.refresh_token,
        access_token_expires_at=result.access_token_expires_at,
        refresh_token_expires_at=result.refresh_token_expires_at,
    )
    return AuthResponse(
        user=_user_response(SimpleNamespace(**selected_values)),
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
    # The dependency has freshly read the account and applied its selected role.
    return _user_response(current_user)
