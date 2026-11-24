"""Cohesive actions operations behind the stable identity route facade."""

from __future__ import annotations

from datetime import UTC

from fastapi import HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.password import hash_password, verify_password
from app.domain.entities.entities import UserRole
from app.infrastructure.database.models import UserModel
from app.infrastructure.observability.metrics import metrics
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.identity_security_repository import (
    IdentitySecurityRepository,
)
from app.infrastructure.repositories.mobile_session_security import revoke_user_mobile_sessions
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository
from app.infrastructure.repositories.user_repository import UserRepository
from app.presentation.api.v1.routes.auth_identity_dependencies import (
    BeginChallenge,
    DateTimeClass,
    PasswordWork,
    SessionIssuer,
)
from app.presentation.api.v1.schemas.auth_schemas import (
    AuthChallengeResponse,
    AuthResponse,
    CompleteIdentityActionRequest,
    IdentityActionCompletedResponse,
)
from app.presentation.security.auth_cookies import (
    clear_auth_cookies,
)
from app.presentation.security.client_ip import trusted_client_ip

_IDENTITY_ACTION_FAILURE = "The link is invalid, expired, or has already been used"


async def _complete_identity_action(
    *,
    body: CompleteIdentityActionRequest,
    request: Request,
    response: Response,
    session: AsyncSession,
    purpose: str,
    datetime: DateTimeClass,
    run_password_work: PasswordWork,
    begin_dashboard_mfa_challenge: BeginChallenge,
    _issue_authenticated_session: SessionIssuer,
) -> AuthResponse | AuthChallengeResponse | IdentityActionCompletedResponse:
    repository = IdentitySecurityRepository(session)
    token = await repository.get_valid_action_token(raw_token=body.token, purpose=purpose)
    now = datetime.now(tz=UTC)
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
    if await run_password_work(verify_password, body.new_password, user.hashed_password):
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
    # Password verification and account contention can cross the link deadline.
    now = datetime.now(tz=UTC)
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
    user.hashed_password = await run_password_work(hash_password, body.new_password)
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
