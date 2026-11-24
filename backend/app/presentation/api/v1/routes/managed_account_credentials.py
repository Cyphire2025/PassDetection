"""Supervised credential/MFA resets and session revocation endpoints."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.password import hash_password, run_password_work
from app.domain.entities.entities import User
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository
from app.presentation.api.v1.routes.managed_account_scope import (
    ACCOUNT_ADMIN_ROLES,
    _get_manageable_account,
)
from app.presentation.api.v1.routes.managed_account_sessions import (
    _fence_coordinator_mobile_sessions,
    _fence_dashboard_sessions,
)
from app.presentation.api.v1.routes.managed_account_values import (
    _account_response,
    _audit_account_action,
)
from app.presentation.api.v1.schemas.operations_schemas import (
    ManagedAccountResponse,
    ResetManagedAccountPasswordRequest,
)
from app.presentation.dependencies.auth import require_recent_mfa, require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.post(
    "/{account_id}/reset-password",
    response_model=ManagedAccountResponse,
    summary="Issue a one-time credential reset link and revoke every existing session",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def reset_managed_account_password(
    account_id: uuid.UUID,
    body: ResetManagedAccountPasswordRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(require_role(ACCOUNT_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ManagedAccountResponse:
    account, agency_name = await _get_manageable_account(session, current_user, account_id)
    del body
    now = datetime.now(tz=UTC)
    account.hashed_password = await run_password_work(
        hash_password, f"Rst1{secrets.token_urlsafe(32)}"
    )
    account.updated_at = now
    repository = IdentitySecurityRepository(session)
    security_state = await repository.get_state(account.id, lock=True)
    if security_state is None:
        security_state = await repository.ensure_state(account)
    security_state.credential_state = "invited"
    security_state.session_version += 1
    security_state.updated_at = now
    await RefreshTokenRepository(session).revoke_all_for_user(account.id)
    await _fence_coordinator_mobile_sessions(
        session,
        account,
        reason="credential_reset",
    )
    _, activation_token = await repository.issue_action_token(
        user_id=account.id,
        purpose="activation",
        expires_in=timedelta(days=7),
        created_by_user_id=current_user.id,
    )
    await _audit_account_action(
        session,
        current_user,
        request,
        account,
        "account.credential_reset_issued",
        metadata={"sessions_revoked": True},
    )
    await session.flush()
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return _account_response(
        account,
        agency_name,
        security_state,
        activation_token=activation_token,
    )


@router.post(
    "/{account_id}/revoke-sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Force an account to sign out on every device",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def revoke_managed_account_sessions(
    account_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(ACCOUNT_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    account, _ = await _get_manageable_account(session, current_user, account_id)
    await _fence_dashboard_sessions(session, account)
    await _audit_account_action(session, current_user, request, account, "account.sessions_revoked")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{account_id}/reset-mfa",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Reset a managed account's MFA and revoke every existing session",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def reset_managed_account_mfa(
    account_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(ACCOUNT_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    account, _ = await _get_manageable_account(session, current_user, account_id)
    repository = IdentitySecurityRepository(session)
    security_state = await repository.get_state(account.id, lock=True)
    if security_state is None:
        security_state = await repository.ensure_state(account)
    await repository.reset_mfa(state=security_state)
    await RefreshTokenRepository(session).revoke_all_for_user(account.id)
    await _fence_coordinator_mobile_sessions(
        session,
        account,
        reason="mfa_reset",
    )
    await _audit_account_action(
        session,
        current_user,
        request,
        account,
        "account.mfa_reset",
        metadata={"sessions_revoked": True, "reenrollment_required": security_state.mfa_required},
    )
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"Cache-Control": "private, no-store, max-age=0", "Pragma": "no-cache"},
    )
