"""Managed account status changes and history-preserving removal."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.password import hash_password, run_password_work
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_models import EmailConnectionModel
from app.infrastructure.database.models import (
    AttendanceRecordModel,
    AttendanceSessionModel,
)
from app.infrastructure.database.session import get_db_session
from app.presentation.api.v1.routes.managed_account_scope import (
    ACCOUNT_ADMIN_ROLES,
    _get_manageable_account,
)
from app.presentation.api.v1.routes.managed_account_sessions import (
    _deactivate_coordinator_assignments,
    _fence_dashboard_sessions,
)
from app.presentation.api.v1.routes.managed_account_values import (
    _account_response,
    _audit_account_action,
)
from app.presentation.api.v1.schemas.operations_schemas import (
    DeleteManagedAccountResponse,
    ManagedAccountResponse,
    SetManagedAccountStatusRequest,
)
from app.presentation.dependencies.auth import require_recent_mfa, require_role
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


@router.patch(
    "/{account_id}/status",
    response_model=ManagedAccountResponse,
    summary="Activate or deactivate a managed account",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def set_managed_account_status(
    account_id: uuid.UUID,
    body: SetManagedAccountStatusRequest,
    request: Request,
    current_user: User = Depends(require_role(ACCOUNT_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ManagedAccountResponse:
    account, agency_name = await _get_manageable_account(session, current_user, account_id)
    account.is_active = body.is_active
    account.updated_at = datetime.now(tz=UTC)
    security_state = await _fence_dashboard_sessions(session, account)
    if not body.is_active:
        await _deactivate_coordinator_assignments(session, account)
    await _audit_account_action(
        session,
        current_user,
        request,
        account,
        "account.activated" if body.is_active else "account.deactivated",
    )
    await session.flush()
    return _account_response(account, agency_name, security_state)


@router.delete(
    "/{account_id}",
    response_model=DeleteManagedAccountResponse,
    summary="Remove a staff or coordinator account while preserving required history",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def delete_managed_account(
    account_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(ACCOUNT_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> DeleteManagedAccountResponse:
    account, _ = await _get_manageable_account(session, current_user, account_id)
    if account.role == UserRole.AGENCY_MANAGER.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Manager accounts must be removed from the manager administration screen",
        )

    email_connection_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(EmailConnectionModel)
                .where(EmailConnectionModel.owner_user_id == account.id)
            )
        ).scalar_one()
    )
    preserves_history = email_connection_count > 0
    if account.role == UserRole.AGENCY_COORDINATOR.value:
        history_count = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(AttendanceRecordModel)
                    .where(AttendanceRecordModel.coordinator_user_id == account.id)
                )
            ).scalar_one()
        )
        session_count = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(AttendanceSessionModel)
                    .where(AttendanceSessionModel.created_by_user_id == account.id)
                )
            ).scalar_one()
        )
        preserves_history = history_count > 0 or session_count > 0
        preserves_history = preserves_history or email_connection_count > 0

    await _fence_dashboard_sessions(session, account)
    await _deactivate_coordinator_assignments(session, account)
    if email_connection_count:
        now = datetime.now(tz=UTC)
        await session.execute(
            update(EmailConnectionModel)
            .where(EmailConnectionModel.owner_user_id == account.id)
            .values(
                status="disconnected",
                sync_state="blocked",
                ai_processing_enabled=False,
                access_token_ciphertext=None,
                refresh_token_ciphertext=None,
                token_expires_at=None,
                sync_cursor=None,
                watch_resource_id=None,
                watch_expiration_at=None,
                sync_lease_token=None,
                sync_lease_expires_at=None,
                sync_generation=EmailConnectionModel.sync_generation + 1,
                next_sync_at=None,
                disconnected_at=now,
                last_error_code="EMAIL_OWNER_ACCOUNT_REMOVED",
                last_error_message="The mailbox owner account was removed.",
                last_error_at=now,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
    await _audit_account_action(
        session,
        current_user,
        request,
        account,
        "account.removed",
        metadata={"preserved_history": preserves_history},
    )
    if preserves_history:
        now = datetime.now(tz=UTC)
        account.is_active = False
        account.email = f"deleted-{account.id}@deleted.invalid"
        account.hashed_password = await run_password_work(hash_password, secrets.token_urlsafe(48))
        account.deleted_at = now
        account.updated_at = now
        result = "deleted"
    else:
        await session.delete(account)
        result = "deleted"
    await session.flush()
    return DeleteManagedAccountResponse(
        account_id=account_id,
        result=result,
        preserved_history=preserves_history,
    )
