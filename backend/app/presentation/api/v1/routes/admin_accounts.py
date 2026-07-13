"""Internal account administration for managers and coordinators."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.password import hash_password
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    AttendanceRecordModel,
    AttendanceSessionModel,
    CoordinatorAssignmentModel,
    CoordinatorGroupAssignmentModel,
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository
from app.presentation.api.v1.schemas.operations_schemas import (
    DeleteManagedAccountResponse,
    ManagedAccountResponse,
    ResetManagedAccountPasswordRequest,
    SetManagedAccountStatusRequest,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()
ACCOUNT_ADMIN_ROLES = [UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_STAFF]
MANAGED_ROLES = (UserRole.AGENCY_STAFF.value, UserRole.AGENCY_COORDINATOR.value)


@router.get("", response_model=list[ManagedAccountResponse], summary="List accounts within the caller's management scope")
async def list_managed_accounts(
    current_user: User = Depends(require_role(ACCOUNT_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[ManagedAccountResponse]:
    filters = [UserModel.role.in_(MANAGED_ROLES)]
    if current_user.role != UserRole.SUPER_ADMIN:
        filters.extend(
            [
                UserModel.role == UserRole.AGENCY_COORDINATOR.value,
                UserModel.agency_id == current_user.agency_id,
            ]
        )
    result = await session.execute(
        select(UserModel, AgencyModel.name.label("agency_name"))
        .outerjoin(AgencyModel, AgencyModel.id == UserModel.agency_id)
        .where(*filters)
        .order_by(UserModel.role.asc(), UserModel.created_at.desc())
    )
    return [_account_response(account, agency_name) for account, agency_name in result.all()]


@router.post(
    "/{account_id}/reset-password",
    response_model=ManagedAccountResponse,
    summary="Set a new password and revoke every existing session",
)
async def reset_managed_account_password(
    account_id: uuid.UUID,
    body: ResetManagedAccountPasswordRequest,
    request: Request,
    current_user: User = Depends(require_role(ACCOUNT_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ManagedAccountResponse:
    account, agency_name = await _get_manageable_account(session, current_user, account_id)
    account.hashed_password = hash_password(body.password)
    account.updated_at = datetime.now(tz=timezone.utc)
    await RefreshTokenRepository(session).revoke_all_for_user(account.id)
    await _audit_account_action(session, current_user, request, account, "account.password_reset")
    await session.flush()
    return _account_response(account, agency_name)


@router.post(
    "/{account_id}/revoke-sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Force an account to sign out on every device",
)
async def revoke_managed_account_sessions(
    account_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(ACCOUNT_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    account, _ = await _get_manageable_account(session, current_user, account_id)
    await RefreshTokenRepository(session).revoke_all_for_user(account.id)
    await _audit_account_action(session, current_user, request, account, "account.sessions_revoked")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch(
    "/{account_id}/status",
    response_model=ManagedAccountResponse,
    summary="Activate or deactivate a managed account",
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
    account.updated_at = datetime.now(tz=timezone.utc)
    if not body.is_active:
        await RefreshTokenRepository(session).revoke_all_for_user(account.id)
        await _deactivate_coordinator_assignments(session, account)
    await _audit_account_action(
        session,
        current_user,
        request,
        account,
        "account.activated" if body.is_active else "account.deactivated",
    )
    await session.flush()
    return _account_response(account, agency_name)


@router.delete(
    "/{account_id}",
    response_model=DeleteManagedAccountResponse,
    summary="Remove a coordinator account while preserving attendance history",
)
async def delete_managed_coordinator(
    account_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(ACCOUNT_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> DeleteManagedAccountResponse:
    account, _ = await _get_manageable_account(session, current_user, account_id)
    if account.role != UserRole.AGENCY_COORDINATOR.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Manager accounts must be removed from the manager administration screen",
        )

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

    await RefreshTokenRepository(session).revoke_all_for_user(account.id)
    await _deactivate_coordinator_assignments(session, account)
    await _audit_account_action(
        session,
        current_user,
        request,
        account,
        "account.removed",
        metadata={"preserved_history": preserves_history},
    )
    if preserves_history:
        account.is_active = False
        account.updated_at = datetime.now(tz=timezone.utc)
        result = "access_removed"
    else:
        await session.delete(account)
        result = "deleted"
    await session.flush()
    return DeleteManagedAccountResponse(
        account_id=account_id,
        result=result,
        preserved_history=preserves_history,
    )


async def _get_manageable_account(
    session: AsyncSession,
    current_user: User,
    account_id: uuid.UUID,
) -> tuple[UserModel, str | None]:
    result = await session.execute(
        select(UserModel, AgencyModel.name.label("agency_name"))
        .outerjoin(AgencyModel, AgencyModel.id == UserModel.agency_id)
        .where(UserModel.id == account_id, UserModel.role.in_(MANAGED_ROLES))
        .with_for_update(of=UserModel)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Managed account was not found")
    account, agency_name = row
    if current_user.role == UserRole.SUPER_ADMIN:
        return account, agency_name
    if account.role != UserRole.AGENCY_COORDINATOR.value or account.agency_id != current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is outside your management scope")
    return account, agency_name


async def _deactivate_coordinator_assignments(session: AsyncSession, account: UserModel) -> None:
    if account.role != UserRole.AGENCY_COORDINATOR.value:
        return
    now = datetime.now(tz=timezone.utc)
    await session.execute(
        update(CoordinatorAssignmentModel)
        .where(
            CoordinatorAssignmentModel.coordinator_user_id == account.id,
            CoordinatorAssignmentModel.active.is_(True),
        )
        .values(active=False, unassigned_at=now)
    )
    await session.execute(
        update(CoordinatorGroupAssignmentModel)
        .where(
            CoordinatorGroupAssignmentModel.coordinator_user_id == account.id,
            CoordinatorGroupAssignmentModel.active.is_(True),
        )
        .values(active=False, unassigned_at=now)
    )


async def _audit_account_action(
    session: AsyncSession,
    current_user: User,
    request: Request,
    account: UserModel,
    action: str,
    metadata: dict[str, object] | None = None,
) -> None:
    await AuditLogRepository(session).record(
        action=action,
        entity_type="user_account",
        agency_id=account.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=str(account.id),
        ip_address=request.client.host if request.client else None,
        metadata={"target_role": account.role, "target_email": account.email, **(metadata or {})},
    )


def _account_response(account: UserModel, agency_name: str | None) -> ManagedAccountResponse:
    return ManagedAccountResponse(
        id=account.id,
        full_name=account.full_name,
        email=account.email,
        role=account.role,
        agency_id=account.agency_id,
        agency_name=agency_name,
        is_active=account.is_active,
        created_at=account.created_at,
        last_login_at=account.last_login_at,
    )
