"""Cohesive account operations behind the stable identity route facade."""

from __future__ import annotations

import uuid
from datetime import UTC

from fastapi import HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.identity_security import (
    generate_recovery_codes,
)
from app.core.security.password import hash_password, verify_password
from app.domain.entities.entities import User, UserRole
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.dashboard_step_up_repository import lock_step_up_session
from app.infrastructure.repositories.identity_security_repository import (
    IdentitySecurityRepository,
)
from app.infrastructure.repositories.mobile_session_security import revoke_user_mobile_sessions
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository
from app.presentation.api.v1.routes.auth_identity_dependencies import (
    DateTimeClass,
    ExistingDeadline,
    PasswordWork,
    SessionIssuer,
)
from app.presentation.api.v1.schemas.auth_schemas import (
    MFARecoveryCodesResponse,
    PasswordChangeRequest,
)
from app.presentation.security.auth_cookies import (
    clear_auth_cookies,
)
from app.presentation.security.client_ip import trusted_client_ip


async def change_dashboard_password(
    body: PasswordChangeRequest,
    request: Request,
    response: Response,
    current_user: User,
    session: AsyncSession,
    *,
    datetime: DateTimeClass,
    run_password_work: PasswordWork,
    _existing_session_deadline: ExistingDeadline,
) -> Response:
    auth_claims = request.state.auth_claims
    locked_session = await lock_step_up_session(
        session,
        user_id=current_user.id,
        session_id=uuid.UUID(auth_claims["sid"]),
        session_version=auth_claims["sv"],
        deadline=_existing_session_deadline(request),
    )
    user = locked_session.user
    if not await run_password_work(verify_password, body.current_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect"
        )
    if await run_password_work(verify_password, body.new_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The new password must be different from the current password",
        )
    state = locked_session.state
    now = datetime.now(tz=UTC)
    user.hashed_password = await run_password_work(hash_password, body.new_password)
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
    await session.commit()
    clear_auth_cookies(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


async def regenerate_mfa_recovery_codes(
    request: Request,
    response: Response,
    current_user: User,
    session: AsyncSession,
    *,
    datetime: DateTimeClass,
    _existing_session_deadline: ExistingDeadline,
    _issue_authenticated_session: SessionIssuer,
) -> MFARecoveryCodesResponse:
    repository = IdentitySecurityRepository(session)
    auth_claims = request.state.auth_claims
    locked_session = await lock_step_up_session(
        session,
        user_id=current_user.id,
        session_id=uuid.UUID(auth_claims["sid"]),
        session_version=auth_claims["sv"],
        deadline=_existing_session_deadline(request),
    )
    state = locked_session.state
    if state.mfa_enabled_at is None:
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
    authentication_methods = auth_claims.get("amr") if isinstance(auth_claims, dict) else None
    factor_method = "pwd"
    if isinstance(authentication_methods, list):
        if "recovery_code" in authentication_methods:
            factor_method = "recovery_code"
        elif "totp" in authentication_methods:
            factor_method = "totp"
    verified_at = auth_claims.get("mfa_at")
    # Rotation does not verify a fresh factor. Retain the signed assurance time
    # and the existing password-only policy for roles where MFA is optional.
    mfa_at = (
        datetime.fromtimestamp(verified_at, tz=UTC)
        if factor_method != "pwd" and isinstance(verified_at, (int, float))
        else None
    )
    await _issue_authenticated_session(
        user=current_user,
        state=state,
        request=request,
        response=response,
        session=session,
        method=factor_method,
        mfa_at=mfa_at,
        session_expires_at=locked_session.deadline,
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
    await session.commit()
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return MFARecoveryCodesResponse(recovery_codes=codes)
