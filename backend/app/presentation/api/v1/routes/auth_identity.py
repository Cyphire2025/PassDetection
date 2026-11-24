"""Workforce invitation, recovery, MFA, and step-up routes."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.auth_dtos import AuthResponseDTO
from app.application.security.access_level_actor import actual_user_agency_id, actual_user_role
from app.application.use_cases.auth.login_use_case import LoginUseCase
from app.core.config.settings import get_settings
from app.core.security.identity_security import (
    IdentitySecurityError,
    build_totp_uri,
    decrypt_mfa_secret,
    encrypt_mfa_secret,
    generate_mfa_secret,
    hash_identity_value,
    verify_totp,
)
from app.core.security.password import run_password_work
from app.core.security.password import verify_password as verify_password
from app.domain.entities.entities import User
from app.infrastructure.database.models import UserModel, UserSecurityStateModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.identity_security_repository import (
    IdentitySecurityRepository,
    role_requires_dashboard_mfa,
)
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.security.identity_recovery_rate_limiter import (
    IdentityRecoveryRateLimiter,
)
from app.infrastructure.security.mfa_step_up_rate_limiter import (
    MFAStepUpRateLimiter,
)
from app.presentation.api.v1.routes import (
    auth_identity_account,
    auth_identity_actions,
    auth_identity_recovery,
    auth_identity_step_up,
    auth_identity_verification,
)
from app.presentation.api.v1.schemas.auth_schemas import (
    AuthChallengeResponse,
    AuthResponse,
    CompleteIdentityActionRequest,
    IdentityActionCompletedResponse,
    MFAChallengeVerifyRequest,
    MFAEnrollmentResult,
    MFARecoveryCodesResponse,
    MFAStepUpRequest,
    PasswordChangeRequest,
    PasswordRecoveryRequest,
    PasswordRecoveryRequestResponse,
)
from app.presentation.dependencies.auth import get_current_active_user, require_recent_mfa
from app.presentation.dependencies.csrf import require_cookie_csrf, require_trusted_request_origin
from app.presentation.security.access_level import clear_access_level_cookie
from app.presentation.security.auth_cookies import (
    set_auth_cookies,
)
from app.presentation.security.auth_user_response import user_response as _user_response
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter()

_MFA_CHALLENGE_FAILURE = "The verification challenge is invalid or expired"


def _request_hash(request: Request, field: str) -> str | None:
    if field == "ip":
        value = trusted_client_ip(request)
    else:
        value = request.headers.get("user-agent")
    if not value:
        return None
    return hash_identity_value(value, purpose=f"request-{field}")


def _login_use_case(session: AsyncSession) -> LoginUseCase:
    return LoginUseCase(
        user_repository=UserRepository(session),
        refresh_token_repository=RefreshTokenRepository(session),
    )


def _auth_response(result: AuthResponseDTO) -> AuthResponse:
    return AuthResponse(
        user=_user_response(result.user),
        token_type=result.token_type,
        access_token_expires_at=result.access_token_expires_at,
    )


async def begin_dashboard_mfa_challenge(
    *,
    user: User,
    request: Request,
    session: AsyncSession,
) -> AuthChallengeResponse | None:
    """Return a durable MFA challenge, or ``None`` when MFA is not required."""

    repository = IdentitySecurityRepository(session)
    state = await repository.get_state(user.id)
    if state is None:
        model = (
            await session.execute(select(UserModel).where(UserModel.id == user.id))
        ).scalar_one()
        state = await repository.ensure_state(model)
    must_use_mfa = state.mfa_required or role_requires_dashboard_mfa(user.role)
    if not must_use_mfa:
        return None
    if not state.mfa_required:
        state.mfa_required = True
        state.updated_at = datetime.now(tz=UTC)

    setup_secret: str | None = None
    otpauth_uri: str | None = None
    pending_secret_ciphertext: str | None = None
    purpose = "mfa_login"
    response_status: Literal["mfa_required", "mfa_enrollment_required"] = "mfa_required"
    if state.mfa_secret_ciphertext is None or state.mfa_enabled_at is None:
        setup_secret = generate_mfa_secret()
        pending_secret_ciphertext = encrypt_mfa_secret(setup_secret)
        otpauth_uri = build_totp_uri(secret=setup_secret, email=user.email)
        purpose = "mfa_enrollment"
        response_status = "mfa_enrollment_required"

    challenge, raw_token = await repository.issue_auth_challenge(
        user_id=user.id,
        purpose=purpose,
        pending_secret_ciphertext=pending_secret_ciphertext,
        request_ip_hash=_request_hash(request, "ip"),
        user_agent_hash=_request_hash(request, "user-agent"),
    )
    await AuditLogRepository(session).record(
        action="auth.mfa_challenge_issued",
        entity_type="user_account",
        agency_id=user.agency_id,
        user_id=user.id,
        actor_email=user.email,
        entity_id=str(user.id),
        ip_address=trusted_client_ip(request),
        metadata={"purpose": purpose},
    )
    return AuthChallengeResponse(
        status=response_status,
        challenge_token=raw_token,
        expires_at=challenge.expires_at,
        setup_secret=setup_secret,
        otpauth_uri=otpauth_uri,
    )


def _existing_session_deadline(request: Request) -> datetime | None:
    claims = getattr(request.state, "auth_claims", {})
    # Legacy signed tokens have no session_exp; retaining their access expiry
    # is conservative until the next original refresh or a fresh sign-in.
    expires = claims.get("session_exp", claims.get("exp"))
    return datetime.fromtimestamp(expires, tz=UTC) if expires is not None else None


async def _issue_authenticated_session(
    *,
    user: User,
    state: UserSecurityStateModel,
    request: Request,
    response: Response,
    session: AsyncSession,
    method: str,
    mfa_at: datetime | None,
    session_expires_at: datetime | None = None,
) -> AuthResponse:
    # The user repository may have loaded the domain entity before this
    # transaction enabled MFA or advanced the credential/session state. Keep
    # the response DTO aligned with the authoritative locked security row.
    user.credential_state = state.credential_state
    user.session_version = state.session_version
    user.mfa_required = state.mfa_required
    user.mfa_enabled = state.mfa_enabled_at is not None
    methods = ("pwd", method) if mfa_at is not None else (method,)
    user = replace(
        user,
        role=actual_user_role(user),
        agency_id=actual_user_agency_id(user),
        actual_role=None,
        actual_agency_id=None,
        access_level_agency_name=None,
    )
    result = await _login_use_case(session).issue_session(
        user,
        client_ip=trusted_client_ip(request),
        session_version=state.session_version,
        authentication_methods=methods,
        mfa_authenticated_at=mfa_at,
        session_expires_at=session_expires_at,
    )
    set_auth_cookies(
        response,
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        access_token_expires_at=result.access_token_expires_at,
        refresh_token_expires_at=result.refresh_token_expires_at,
    )
    clear_access_level_cookie(response)
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return _auth_response(result)


async def _validate_mfa_code(
    *,
    repository: IdentitySecurityRepository,
    state: UserSecurityStateModel,
    code: str,
    secret_ciphertext: str,
    now: datetime,
    allow_recovery: bool,
) -> tuple[bool, str, int | None]:
    try:
        secret = decrypt_mfa_secret(secret_ciphertext)
    except IdentitySecurityError:
        return False, "totp", None
    counter = verify_totp(
        secret,
        code.strip(),
        now=now,
        last_accepted_counter=state.mfa_last_counter,
    )
    if counter is not None:
        return True, "totp", counter
    if allow_recovery and await repository.consume_recovery_code(
        user_id=state.user_id,
        raw_code=code,
        now=now,
    ):
        return True, "recovery_code", None
    return False, "totp", None


async def _deny_mfa_verification(session: AsyncSession) -> NoReturn:
    """Keep guarded denial state durable when the request dependency rolls back."""
    await session.commit()
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_MFA_CHALLENGE_FAILURE)


@router.post(
    "/mfa/verify",
    response_model=MFAEnrollmentResult | AuthResponse,
    dependencies=[Depends(require_trusted_request_origin)],
)
async def verify_dashboard_mfa(
    body: MFAChallengeVerifyRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> MFAEnrollmentResult | AuthResponse:
    return await auth_identity_verification.verify_dashboard_mfa(
        body=body,
        request=request,
        response=response,
        session=session,
        datetime=datetime,
        _request_hash=_request_hash,
        _validate_mfa_code=_validate_mfa_code,
        _issue_authenticated_session=_issue_authenticated_session,
        _deny_mfa_verification=_deny_mfa_verification,
    )


@router.post(
    "/mfa/step-up",
    response_model=AuthResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def step_up_dashboard_session(
    body: MFAStepUpRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> AuthResponse:
    return await auth_identity_step_up.step_up_dashboard_session(
        body=body,
        request=request,
        response=response,
        current_user=current_user,
        session=session,
        datetime=datetime,
        get_settings=get_settings,
        MFAStepUpRateLimiter=MFAStepUpRateLimiter,
        _existing_session_deadline=_existing_session_deadline,
        _validate_mfa_code=_validate_mfa_code,
    )


@router.post(
    "/activate",
    response_model=AuthResponse | AuthChallengeResponse | IdentityActionCompletedResponse,
    dependencies=[Depends(require_trusted_request_origin)],
)
async def activate_dashboard_account(
    body: CompleteIdentityActionRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> AuthResponse | AuthChallengeResponse | IdentityActionCompletedResponse:
    result = await _complete_identity_action(
        body=body,
        request=request,
        response=response,
        session=session,
        purpose="activation",
    )
    await session.commit()
    return result


@router.post(
    "/password/recovery/request",
    response_model=PasswordRecoveryRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_trusted_request_origin)],
)
async def request_password_recovery(
    body: PasswordRecoveryRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> PasswordRecoveryRequestResponse:
    return await auth_identity_recovery.request_password_recovery(
        body=body,
        request=request,
        response=response,
        session=session,
        get_settings=get_settings,
        IdentityRecoveryRateLimiter=IdentityRecoveryRateLimiter,
        _request_hash=_request_hash,
    )


@router.post(
    "/password/recovery/complete",
    response_model=AuthResponse | AuthChallengeResponse | IdentityActionCompletedResponse,
    dependencies=[Depends(require_trusted_request_origin)],
)
async def complete_password_recovery(
    body: CompleteIdentityActionRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> AuthResponse | AuthChallengeResponse | IdentityActionCompletedResponse:
    result = await _complete_identity_action(
        body=body,
        request=request,
        response=response,
        session=session,
        purpose="password_recovery",
    )
    await session.commit()
    return result


async def _complete_identity_action(
    *,
    body: CompleteIdentityActionRequest,
    request: Request,
    response: Response,
    session: AsyncSession,
    purpose: str,
) -> AuthResponse | AuthChallengeResponse | IdentityActionCompletedResponse:
    return await auth_identity_actions._complete_identity_action(
        body=body,
        request=request,
        response=response,
        session=session,
        purpose=purpose,
        datetime=datetime,
        run_password_work=run_password_work,
        begin_dashboard_mfa_challenge=begin_dashboard_mfa_challenge,
        _issue_authenticated_session=_issue_authenticated_session,
    )


@router.post(
    "/password/change",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_cookie_csrf)],
)
async def change_dashboard_password(
    body: PasswordChangeRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(require_recent_mfa),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    return await auth_identity_account.change_dashboard_password(
        body=body,
        request=request,
        response=response,
        current_user=current_user,
        session=session,
        datetime=datetime,
        run_password_work=run_password_work,
        _existing_session_deadline=_existing_session_deadline,
    )


@router.post(
    "/mfa/recovery-codes/regenerate",
    response_model=MFARecoveryCodesResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def regenerate_mfa_recovery_codes(
    request: Request,
    response: Response,
    current_user: User = Depends(require_recent_mfa),
    session: AsyncSession = Depends(get_db_session),
) -> MFARecoveryCodesResponse:
    return await auth_identity_account.regenerate_mfa_recovery_codes(
        request=request,
        response=response,
        current_user=current_user,
        session=session,
        datetime=datetime,
        _existing_session_deadline=_existing_session_deadline,
        _issue_authenticated_session=_issue_authenticated_session,
    )


__all__ = ["begin_dashboard_mfa_challenge", "router"]
