"""Workforce invitation, recovery, MFA, and step-up routes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.auth_dtos import AuthResponseDTO
from app.application.interfaces.identity_notification_provider import (
    IdentityNotificationDeliveryDisabled,
)
from app.application.use_cases.auth.login_use_case import LoginUseCase
from app.core.config.settings import get_settings
from app.core.security.identity_security import (
    IdentitySecurityError,
    build_totp_uri,
    decrypt_mfa_secret,
    encrypt_mfa_secret,
    generate_mfa_secret,
    generate_recovery_codes,
    hash_identity_value,
    reencrypt_mfa_secret_if_needed,
    verify_totp,
)
from app.core.security.jwt import create_access_token
from app.core.security.password import hash_password, verify_password
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import UserModel, UserSecurityStateModel
from app.infrastructure.database.session import get_db_session
from app.infrastructure.observability.metrics import metrics
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.identity_security_repository import (
    IdentitySecurityRepository,
    role_requires_dashboard_mfa,
)
from app.infrastructure.repositories.mobile_session_security import revoke_user_mobile_sessions
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.security.identity_notifications import (
    identity_notification_provider,
    stage_password_recovery_notification,
)
from app.infrastructure.security.identity_recovery_rate_limiter import (
    IdentityRecoveryRateLimited,
    IdentityRecoveryRateLimiter,
    IdentityRecoveryRateLimiterUnavailable,
)
from app.infrastructure.security.mfa_step_up_rate_limiter import (
    MFAStepUpLimiterUnavailable,
    MFAStepUpLocked,
    MFAStepUpRateLimiter,
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
    UserResponse,
)
from app.presentation.dependencies.auth import get_current_active_user, require_recent_mfa
from app.presentation.dependencies.csrf import require_cookie_csrf, require_trusted_request_origin
from app.presentation.security.auth_cookies import (
    clear_auth_cookies,
    set_access_cookie,
    set_auth_cookies,
)
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter()

_IDENTITY_ACTION_FAILURE = "The link is invalid, expired, or has already been used"
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


def _user_response(user: object) -> UserResponse:
    values = dict(vars(user))
    raw_role = values.get("role")
    role = raw_role.value if isinstance(raw_role, UserRole) else raw_role
    is_active = values.get("is_active") is True
    agency_id = values.get("agency_id")
    can_manage_gc_app = is_active and (
        role == UserRole.SUPER_ADMIN.value
        or (
            role in {UserRole.AGENCY_ADMIN.value, UserRole.AGENCY_MANAGER.value}
            and agency_id is not None
        )
    )
    values["capabilities"] = ["gc_app.manage"] if can_manage_gc_app else []
    return UserResponse.model_validate(values)


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


async def _issue_authenticated_session(
    *,
    user: User,
    state: UserSecurityStateModel,
    request: Request,
    response: Response,
    session: AsyncSession,
    method: str,
    mfa_at: datetime | None,
) -> AuthResponse:
    # The user repository may have loaded the domain entity before this
    # transaction enabled MFA or advanced the credential/session state. Keep
    # the response DTO aligned with the authoritative locked security row.
    user.credential_state = state.credential_state
    user.session_version = state.session_version
    user.mfa_required = state.mfa_required
    user.mfa_enabled = state.mfa_enabled_at is not None
    methods = ("pwd", method) if mfa_at is not None else (method,)
    result = await _login_use_case(session).issue_session(
        user,
        client_ip=trusted_client_ip(request),
        session_version=state.session_version,
        authentication_methods=methods,
        mfa_authenticated_at=mfa_at,
    )
    set_auth_cookies(
        response,
        access_token=result.access_token,
        refresh_token=result.refresh_token,
    )
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
    repository = IdentitySecurityRepository(session)
    now = datetime.now(tz=UTC)
    challenge = await repository.get_pending_auth_challenge(
        raw_token=body.challenge_token,
        now=now,
    )
    if challenge is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_MFA_CHALLENGE_FAILURE)
    if challenge.request_ip_hash != _request_hash(
        request, "ip"
    ) or challenge.user_agent_hash != _request_hash(request, "user-agent"):
        challenge.status = "cancelled"
        challenge.updated_at = now
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_MFA_CHALLENGE_FAILURE)

    state = await repository.get_state(challenge.user_id, lock=True)
    if state is None or state.credential_state != "active":
        challenge.status = "cancelled"
        challenge.updated_at = now
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_MFA_CHALLENGE_FAILURE)
    user = await UserRepository(session).get_by_id(challenge.user_id)
    if user is None or not user.is_active:
        challenge.status = "cancelled"
        challenge.updated_at = now
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_MFA_CHALLENGE_FAILURE)

    secret_ciphertext = (
        challenge.pending_secret_ciphertext
        if challenge.purpose == "mfa_enrollment"
        else state.mfa_secret_ciphertext
    )
    if secret_ciphertext is None:
        challenge.status = "cancelled"
        challenge.updated_at = now
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_MFA_CHALLENGE_FAILURE)
    valid, method, counter = await _validate_mfa_code(
        repository=repository,
        state=state,
        code=body.code,
        secret_ciphertext=secret_ciphertext,
        now=now,
        allow_recovery=challenge.purpose == "mfa_login",
    )
    if not valid:
        challenge.attempt_count += 1
        challenge.updated_at = now
        if challenge.attempt_count >= challenge.max_attempts:
            challenge.status = "locked"
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_MFA_CHALLENGE_FAILURE)

    recovery_codes: list[str] = []
    if challenge.purpose == "mfa_enrollment":
        state.mfa_secret_ciphertext = secret_ciphertext
        state.mfa_enabled_at = now
        state.session_version += 1
        recovery_codes = generate_recovery_codes()
        await repository.replace_recovery_codes(user_id=user.id, raw_codes=recovery_codes, now=now)
    elif state.mfa_secret_ciphertext is not None:
        # Successful verification is the safest lazy-rotation point: the state
        # row is locked and the old key has just authenticated one real factor.
        state.mfa_secret_ciphertext = reencrypt_mfa_secret_if_needed(state.mfa_secret_ciphertext)
    state.mfa_last_counter = counter if counter is not None else state.mfa_last_counter
    state.updated_at = now
    challenge.status = "consumed"
    challenge.consumed_at = now
    challenge.updated_at = now
    auth_response = await _issue_authenticated_session(
        user=user,
        state=state,
        request=request,
        response=response,
        session=session,
        method=method,
        mfa_at=now,
    )
    await AuditLogRepository(session).record(
        action="auth.mfa_enrolled" if recovery_codes else "auth.mfa_verified",
        entity_type="user_account",
        agency_id=user.agency_id,
        user_id=user.id,
        actor_email=user.email,
        entity_id=str(user.id),
        ip_address=trusted_client_ip(request),
        metadata={"method": method},
    )
    if recovery_codes:
        return MFAEnrollmentResult(**auth_response.model_dump(), recovery_codes=recovery_codes)
    return auth_response


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
    client_ip = trusted_client_ip(request)
    limiter = MFAStepUpRateLimiter()
    try:
        await limiter.ensure_available(user_id=current_user.id, ip_address=client_ip)
    except MFAStepUpLocked:
        await limiter.close()
        await AuditLogRepository(session).record(
            action="auth.step_up_blocked",
            entity_type="user_account",
            agency_id=current_user.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            entity_id=str(current_user.id),
            ip_address=client_ip,
            result="blocked",
            metadata={"reason": "temporary_backoff"},
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Verification is temporarily unavailable after repeated attempts",
            headers={"Retry-After": str(get_settings().mfa_step_up_lock_seconds)},
        ) from None
    except MFAStepUpLimiterUnavailable:
        await limiter.close()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Verification is temporarily unavailable",
            headers={"Retry-After": "30"},
        ) from None

    repository = IdentitySecurityRepository(session)
    state = await repository.get_state(current_user.id, lock=True)
    now = datetime.now(tz=UTC)
    if state is None or state.mfa_secret_ciphertext is None or state.mfa_enabled_at is None:
        await limiter.close()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="MFA enrollment is required"
        )
    valid, method, counter = await _validate_mfa_code(
        repository=repository,
        state=state,
        code=body.code,
        secret_ciphertext=state.mfa_secret_ciphertext,
        now=now,
        allow_recovery=True,
    )
    if not valid:
        temporarily_locked = False
        try:
            await limiter.record_failure(user_id=current_user.id, ip_address=client_ip)
        except MFAStepUpLocked:
            temporarily_locked = True
        except MFAStepUpLimiterUnavailable:
            # The factor still failed. Preserve that safe decision and report a
            # generic outage rather than allowing unbounded guesses.
            temporarily_locked = True
        await limiter.close()
        await AuditLogRepository(session).record(
            action="auth.step_up_failed",
            entity_type="user_account",
            agency_id=current_user.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            entity_id=str(current_user.id),
            ip_address=client_ip,
            result="failed",
            metadata={"temporary_backoff": temporarily_locked},
        )
        await session.commit()
        if temporarily_locked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Verification is temporarily unavailable after repeated attempts",
                headers={"Retry-After": str(get_settings().mfa_step_up_lock_seconds)},
            ) from None
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Verification code is invalid",
        )
    await limiter.clear(user_id=current_user.id, ip_address=client_ip)
    state.mfa_secret_ciphertext = reencrypt_mfa_secret_if_needed(state.mfa_secret_ciphertext)
    state.mfa_last_counter = counter if counter is not None else state.mfa_last_counter
    state.updated_at = now
    access_token, access_expires = create_access_token(
        user_id=current_user.id,
        role=current_user.role.value,
        agency_id=current_user.agency_id,
        session_version=state.session_version,
        authentication_methods=("pwd", method),
        mfa_authenticated_at=now,
    )
    set_access_cookie(response, access_token=access_token)
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    await AuditLogRepository(session).record(
        action="auth.step_up_completed",
        entity_type="user_account",
        agency_id=current_user.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=str(current_user.id),
        ip_address=client_ip,
        metadata={"method": method},
    )
    values = dict(vars(current_user))
    values["mfa_required"] = state.mfa_required
    values["mfa_enabled"] = state.mfa_enabled_at is not None
    return AuthResponse(
        user=_user_response(SimpleNamespace(**values)),
        access_token_expires_at=access_expires,
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
    return await _complete_identity_action(
        body=body,
        request=request,
        response=response,
        session=session,
        purpose="activation",
    )


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
    settings = get_settings()
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    neutral_response = PasswordRecoveryRequestResponse(development_recovery_token=None)
    limiter = IdentityRecoveryRateLimiter()
    try:
        await limiter.consume_network(
            ip_address=trusted_client_ip(request),
            risk_context=_request_hash(request, "user-agent"),
        )
        # Provider construction performs configuration validation without
        # delivering anything. A disabled/misconfigured production integration
        # must never mint a raw token that nobody can receive.
        identity_notification_provider(settings)
    except (
        IdentityNotificationDeliveryDisabled,
        IdentityRecoveryRateLimited,
        IdentityRecoveryRateLimiterUnavailable,
    ):
        metrics.increment("identity.password_recovery.request_suppressed")
        await limiter.close()
        return neutral_response

    email = str(body.email).lower().strip()
    user = (
        await session.execute(
            select(UserModel).where(
                UserModel.email == email,
                UserModel.is_active.is_(True),
                UserModel.deleted_at.is_(None),
                UserModel.role != UserRole.CLIENT_MANAGER.value,
            )
        )
    ).scalar_one_or_none()
    development_token: str | None = None
    if user is not None:
        account_limiter = IdentityRecoveryRateLimiter()
        try:
            await account_limiter.consume_account(user_id=user.id, agency_id=user.agency_id)
        except (IdentityRecoveryRateLimited, IdentityRecoveryRateLimiterUnavailable):
            # Preserve any previously issued link. This suppression is audited
            # internally but remains indistinguishable to the requester.
            await AuditLogRepository(session).record(
                action="auth.password_recovery_suppressed",
                entity_type="user_account",
                agency_id=user.agency_id,
                user_id=user.id,
                entity_id=str(user.id),
                ip_address=trusted_client_ip(request),
                result="blocked",
                metadata={"reason": "bounded_rate_limit"},
            )
            metrics.increment("identity.password_recovery.account_suppressed")
            await limiter.close()
            return neutral_response
        repository = IdentitySecurityRepository(session)
        state = await repository.ensure_state(user)
        if state.credential_state == "active":
            action_token, raw_token = await repository.issue_action_token(
                user_id=user.id,
                purpose="password_recovery",
                expires_in=timedelta(minutes=settings.password_recovery_token_ttl_minutes),
                request_ip_hash=_request_hash(request, "ip"),
            )
            stage_password_recovery_notification(
                session,
                user=user,
                action_token=action_token,
                raw_token=raw_token,
                settings=settings,
            )
            if settings.is_development and settings.password_recovery_development_expose_token:
                development_token = raw_token
            await AuditLogRepository(session).record(
                action="auth.password_recovery_requested",
                entity_type="user_account",
                agency_id=user.agency_id,
                user_id=user.id,
                actor_email=user.email,
                entity_id=str(user.id),
                ip_address=trusted_client_ip(request),
                metadata={
                    "delivery_staged": True,
                    "expires_in_minutes": settings.password_recovery_token_ttl_minutes,
                },
            )
    await limiter.close()
    return PasswordRecoveryRequestResponse(development_recovery_token=development_token)


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
    return await _complete_identity_action(
        body=body,
        request=request,
        response=response,
        session=session,
        purpose="password_recovery",
    )


async def _complete_identity_action(
    *,
    body: CompleteIdentityActionRequest,
    request: Request,
    response: Response,
    session: AsyncSession,
    purpose: str,
) -> AuthResponse | AuthChallengeResponse | IdentityActionCompletedResponse:
    repository = IdentitySecurityRepository(session)
    now = datetime.now(tz=UTC)
    token = await repository.get_valid_action_token(raw_token=body.token, purpose=purpose, now=now)
    if token is None:
        metrics.increment("identity.action.redemption_rejected")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_IDENTITY_ACTION_FAILURE
        )
    user = (
        await session.execute(
            select(UserModel)
            .where(
                UserModel.id == token.user_id,
                UserModel.is_active.is_(True),
                UserModel.deleted_at.is_(None),
                UserModel.role != UserRole.CLIENT_MANAGER.value,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    state = await repository.get_state(token.user_id, lock=True)
    if user is None or state is None:
        token.invalidated_at = now
        await AuditLogRepository(session).record(
            action="auth.identity_action_blocked",
            entity_type="identity_action",
            agency_id=user.agency_id if user is not None else None,
            user_id=token.user_id,
            entity_id=str(token.id),
            ip_address=trusted_client_ip(request),
            result="blocked",
            metadata={"purpose": purpose, "reason": "account_not_eligible"},
        )
        # The request must fail, but the authoritative invalidation and its
        # privacy-safe evidence must not be rolled back with the HTTP error.
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_IDENTITY_ACTION_FAILURE
        )
    if purpose == "activation" and state.credential_state != "invited":
        token.invalidated_at = now
        await AuditLogRepository(session).record(
            action="auth.identity_action_blocked",
            entity_type="identity_action",
            agency_id=user.agency_id,
            user_id=user.id,
            actor_email=user.email,
            entity_id=str(token.id),
            ip_address=trusted_client_ip(request),
            result="blocked",
            metadata={"purpose": purpose, "reason": "credential_state_mismatch"},
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_IDENTITY_ACTION_FAILURE
        )
    if verify_password(body.new_password, user.hashed_password):
        await AuditLogRepository(session).record(
            action="auth.identity_action_failed",
            entity_type="identity_action",
            agency_id=user.agency_id,
            user_id=user.id,
            actor_email=user.email,
            entity_id=str(token.id),
            ip_address=trusted_client_ip(request),
            result="failed",
            metadata={"purpose": purpose, "reason": "password_reuse"},
        )
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Choose a password you have not just used",
        )
    if not await repository.consume_action_token(
        token_id=token.id,
        purpose=purpose,
        now=now,
    ):
        metrics.increment("identity.action.concurrent_redemption_rejected")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_IDENTITY_ACTION_FAILURE,
        )
    user.hashed_password = hash_password(body.new_password)
    user.updated_at = now
    state.credential_state = "active"
    state.password_changed_at = now
    state.session_version += 1
    state.updated_at = now
    token.consumed_at = now
    await RefreshTokenRepository(session).revoke_all_for_user(user.id)
    if user.role == UserRole.AGENCY_COORDINATOR.value and user.agency_id is not None:
        await revoke_user_mobile_sessions(
            session,
            agency_id=user.agency_id,
            user_id=user.id,
            subject_role="coordinator",
            reason=f"{purpose}_completed",
            now=now,
        )
    await session.flush()
    domain_user = await UserRepository(session).get_by_id(user.id)
    if domain_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_IDENTITY_ACTION_FAILURE
        )
    await AuditLogRepository(session).record(
        action="auth.account_activated" if purpose == "activation" else "auth.password_recovered",
        entity_type="user_account",
        agency_id=user.agency_id,
        user_id=user.id,
        actor_email=user.email,
        entity_id=str(user.id),
        ip_address=trusted_client_ip(request),
        metadata={"sessions_revoked": True},
    )
    if domain_user.role == UserRole.AGENCY_COORDINATOR:
        clear_auth_cookies(response)
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return IdentityActionCompletedResponse(
            message=(
                "Your account is active. Return to the coordinator app and sign in with "
                "your new password."
            )
        )
    challenge = await begin_dashboard_mfa_challenge(
        user=domain_user,
        request=request,
        session=session,
    )
    if challenge is not None:
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return challenge
    return await _issue_authenticated_session(
        user=domain_user,
        state=state,
        request=request,
        response=response,
        session=session,
        method=purpose,
        mfa_at=None,
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
    user = (
        await session.execute(
            select(UserModel).where(UserModel.id == current_user.id).with_for_update()
        )
    ).scalar_one()
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect"
        )
    if verify_password(body.new_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The new password must be different from the current password",
        )
    repository = IdentitySecurityRepository(session)
    state = await repository.get_state(user.id, lock=True)
    if state is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is no longer valid"
        )
    now = datetime.now(tz=UTC)
    user.hashed_password = hash_password(body.new_password)
    user.updated_at = now
    state.password_changed_at = now
    state.session_version += 1
    state.updated_at = now
    await RefreshTokenRepository(session).revoke_all_for_user(user.id)
    if current_user.role == UserRole.AGENCY_COORDINATOR and user.agency_id is not None:
        await revoke_user_mobile_sessions(
            session,
            agency_id=user.agency_id,
            user_id=user.id,
            subject_role="coordinator",
            reason="password_changed",
            now=now,
        )
    await AuditLogRepository(session).record(
        action="auth.password_changed",
        entity_type="user_account",
        agency_id=current_user.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=str(current_user.id),
        ip_address=trusted_client_ip(request),
        metadata={"sessions_revoked": True},
    )
    clear_auth_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


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
    repository = IdentitySecurityRepository(session)
    state = await repository.get_state(current_user.id, lock=True)
    if state is None or state.mfa_enabled_at is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="MFA is not enabled")
    now = datetime.now(tz=UTC)
    codes = generate_recovery_codes()
    await repository.replace_recovery_codes(
        user_id=current_user.id,
        raw_codes=codes,
        now=now,
    )
    # Recovery codes are authentication factors. Rotate the session generation
    # and revoke every existing refresh token when they change, then mint one
    # replacement session for the recently MFA-verified caller.
    state.session_version += 1
    state.updated_at = now
    await RefreshTokenRepository(session).revoke_all_for_user(current_user.id)
    auth_claims = getattr(request.state, "auth_claims", {})
    authentication_methods = auth_claims.get("amr") if isinstance(auth_claims, dict) else None
    factor_method = (
        "recovery_code"
        if isinstance(authentication_methods, list) and "recovery_code" in authentication_methods
        else "totp"
    )
    await _issue_authenticated_session(
        user=current_user,
        state=state,
        request=request,
        response=response,
        session=session,
        method=factor_method,
        mfa_at=now,
    )
    await AuditLogRepository(session).record(
        action="auth.mfa_recovery_codes_regenerated",
        entity_type="user_account",
        agency_id=current_user.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=str(current_user.id),
        ip_address=trusted_client_ip(request),
        metadata={"sessions_revoked": True, "current_session_rotated": True},
    )
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return MFARecoveryCodesResponse(recovery_codes=codes)


__all__ = ["begin_dashboard_mfa_challenge", "router"]
