"""Cohesive step up operations behind the stable identity route facade."""

from __future__ import annotations

import uuid
from datetime import UTC
from types import SimpleNamespace

from fastapi import HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.security.access_level_actor import actual_user_agency_id, actual_user_role
from app.core.security.identity_security import (
    reencrypt_mfa_secret_if_needed,
)
from app.core.security.jwt import create_access_token
from app.domain.entities.entities import User
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.dashboard_step_up_repository import lock_step_up_session
from app.infrastructure.repositories.identity_security_repository import (
    IdentitySecurityRepository,
)
from app.infrastructure.security.mfa_step_up_rate_limiter import (
    MFAStepUpLimiterUnavailable,
    MFAStepUpLocked,
)
from app.presentation.api.v1.routes.auth_identity_dependencies import (
    DateTimeClass,
    ExistingDeadline,
    FactorVerifier,
    SettingsProvider,
    StepUpLimiterFactory,
)
from app.presentation.api.v1.schemas.auth_schemas import (
    AuthResponse,
    MFAStepUpRequest,
)
from app.presentation.security.auth_cookies import (
    set_access_cookie,
)
from app.presentation.security.auth_user_response import user_response as _user_response
from app.presentation.security.client_ip import trusted_client_ip


async def step_up_dashboard_session(
    body: MFAStepUpRequest,
    request: Request,
    response: Response,
    current_user: User,
    session: AsyncSession,
    *,
    datetime: DateTimeClass,
    get_settings: SettingsProvider,
    MFAStepUpRateLimiter: StepUpLimiterFactory,
    _existing_session_deadline: ExistingDeadline,
    _validate_mfa_code: FactorVerifier,
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
    try:
        stepped_session = await lock_step_up_session(
            session,
            user_id=current_user.id,
            session_id=uuid.UUID(request.state.auth_claims["sid"]),
            session_version=request.state.auth_claims["sv"],
            deadline=_existing_session_deadline(request),
        )
    except Exception:
        await limiter.close()
        raise
    state = stepped_session.state
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
    await limiter.close()
    state.mfa_secret_ciphertext = reencrypt_mfa_secret_if_needed(state.mfa_secret_ciphertext)
    state.mfa_last_counter = counter if counter is not None else state.mfa_last_counter
    state.updated_at = now
    stepped_session.record_assurance(method=method, now=now)
    # A fresh factor authorizes this action; it must not extend the browser's
    # sign-in deadline. Legacy access tokens retain their existing expiry.
    access_token, access_expires = create_access_token(
        user_id=current_user.id,
        role=actual_user_role(current_user).value,
        agency_id=actual_user_agency_id(current_user),
        session_version=state.session_version,
        authentication_methods=("pwd", method),
        mfa_authenticated_at=now,
        session_expires_at=stepped_session.deadline,
        session_id=uuid.UUID(request.state.auth_claims["sid"]),
    )
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
    # Factor consumption, refresh assurance and audit must be durable before
    # the response can publish a cookie asserting that verification succeeded.
    await session.commit()
    set_access_cookie(response, access_token=access_token, expires_at=access_expires)
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    values = dict(vars(current_user))
    values["mfa_required"] = state.mfa_required
    values["mfa_enabled"] = state.mfa_enabled_at is not None
    return AuthResponse(
        user=_user_response(SimpleNamespace(**values)),
        access_token_expires_at=access_expires,
    )
