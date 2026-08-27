"""Internal account administration for managers and coordinators."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.core.security.password import hash_password
from app.domain.entities.entities import User, UserRole
from app.infrastructure.database.email_models import EmailConnectionModel
from app.infrastructure.database.models import (
    AgencyModel,
    AttendanceRecordModel,
    AttendanceSessionModel,
    ClientGroupModel,
    CoordinatorAssignmentModel,
    CoordinatorGroupAssignmentModel,
    UserModel,
    UserSecurityStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.infrastructure.repositories.mobile_session_security import revoke_user_mobile_sessions
from app.infrastructure.repositories.refresh_token_repository import RefreshTokenRepository
from app.presentation.api.v1.schemas.operations_schemas import (
    CreateStaffRequest,
    DeleteManagedAccountResponse,
    ManagedAccountResponse,
    ResetManagedAccountPasswordRequest,
    SetManagedAccountStatusRequest,
)
from app.presentation.dependencies.auth import require_recent_mfa, require_role
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter()
ACCOUNT_ADMIN_ROLES = [UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER]
STAFF_ADMIN_ROLES = [UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER]
MANAGED_ROLES = (
    UserRole.AGENCY_MANAGER.value,
    UserRole.AGENCY_STAFF.value,
    UserRole.AGENCY_COORDINATOR.value,
)
LISTED_ACCOUNT_ROLES = (UserRole.AGENCY_STAFF.value, UserRole.AGENCY_COORDINATOR.value)

_CredentialState = Literal["invited", "active"]


def _validated_credential_state(value: str) -> _CredentialState:
    if value not in {"invited", "active"}:
        raise RuntimeError("Invalid persisted workforce credential state.")
    return cast(_CredentialState, value)


@router.get(
    "",
    response_model=list[ManagedAccountResponse],
    summary="List accounts within the caller's management scope",
)
async def list_managed_accounts(
    current_user: User = Depends(require_role(ACCOUNT_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[ManagedAccountResponse]:
    filters: list[ColumnElement[bool]] = [
        UserModel.role.in_(LISTED_ACCOUNT_ROLES),
        UserModel.deleted_at.is_(None),
    ]
    if current_user.role == UserRole.AGENCY_ADMIN:
        filters.extend(
            [
                UserModel.role.in_(
                    (UserRole.AGENCY_STAFF.value, UserRole.AGENCY_COORDINATOR.value)
                ),
                UserModel.agency_id == current_user.agency_id,
            ]
        )
    elif current_user.role == UserRole.AGENCY_MANAGER:
        filters.extend(
            [
                UserModel.role == UserRole.AGENCY_COORDINATOR.value,
                UserModel.agency_id == current_user.agency_id,
            ]
        )
    result = await session.execute(
        select(UserModel, AgencyModel.name.label("agency_name"), UserSecurityStateModel)
        .outerjoin(AgencyModel, AgencyModel.id == UserModel.agency_id)
        .outerjoin(UserSecurityStateModel, UserSecurityStateModel.user_id == UserModel.id)
        .where(*filters)
        .order_by(UserModel.role.asc(), UserModel.created_at.desc())
    )
    return [
        _account_response(account, agency_name, security_state)
        for account, agency_name, security_state in result.all()
    ]


@router.get("/staff", response_model=list[ManagedAccountResponse], summary="List staff accounts")
async def list_staff_accounts(
    current_user: User = Depends(require_role(STAFF_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> list[ManagedAccountResponse]:
    filters = [
        UserModel.role == UserRole.AGENCY_STAFF.value,
        UserModel.deleted_at.is_(None),
    ]
    if current_user.role != UserRole.SUPER_ADMIN:
        filters.append(UserModel.agency_id == current_user.agency_id)
    result = await session.execute(
        select(UserModel, AgencyModel.name.label("agency_name"), UserSecurityStateModel)
        .outerjoin(AgencyModel, AgencyModel.id == UserModel.agency_id)
        .outerjoin(UserSecurityStateModel, UserSecurityStateModel.user_id == UserModel.id)
        .where(*filters)
        .order_by(UserModel.created_at.desc())
    )
    return [
        _account_response(account, agency_name, security_state)
        for account, agency_name, security_state in result.all()
    ]


@router.post(
    "/staff",
    response_model=ManagedAccountResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a staff account",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def create_staff_account(
    body: CreateStaffRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(require_role(STAFF_ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db_session),
) -> ManagedAccountResponse:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Assign the admin to an agency before creating staff",
        )

    email = str(body.email).lower().strip()
    existing = await session.execute(select(UserModel).where(UserModel.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists"
        )

    staff = UserModel(
        email=email,
        hashed_password=hash_password(f"Inv1{secrets.token_urlsafe(32)}"),
        full_name=body.full_name.strip(),
        role=UserRole.AGENCY_STAFF.value,
        agency_id=current_user.agency_id,
        is_active=True,
    )
    session.add(staff)
    await session.flush()
    identity_repository = IdentitySecurityRepository(session)
    security_state = UserSecurityStateModel(
        user_id=staff.id,
        credential_state="invited",
        session_version=1,
        mfa_required=True,
    )
    session.add(security_state)
    _, activation_token = await identity_repository.issue_action_token(
        user_id=staff.id,
        purpose="activation",
        expires_in=timedelta(days=7),
        created_by_user_id=current_user.id,
    )
    await _audit_account_action(session, current_user, request, staff, "staff.invited")

    agency_name = None
    if staff.agency_id:
        agency_name = (
            await session.execute(select(AgencyModel.name).where(AgencyModel.id == staff.agency_id))
        ).scalar_one_or_none()
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return _account_response(
        staff,
        agency_name,
        security_state,
        activation_token=activation_token,
    )


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
    account.hashed_password = hash_password(f"Rst1{secrets.token_urlsafe(32)}")
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
    await _fence_dashboard_sessions(session, account)
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
    return _account_response(account, agency_name)


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
        account.hashed_password = hash_password(secrets.token_urlsafe(48))
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


async def _get_manageable_account(
    session: AsyncSession,
    current_user: User,
    account_id: uuid.UUID,
) -> tuple[UserModel, str | None]:
    result = await session.execute(
        select(UserModel, AgencyModel.name.label("agency_name"))
        .outerjoin(AgencyModel, AgencyModel.id == UserModel.agency_id)
        .where(
            UserModel.id == account_id,
            UserModel.role.in_(MANAGED_ROLES),
            UserModel.deleted_at.is_(None),
        )
        .with_for_update(of=UserModel)
    )
    row = result.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Managed account was not found"
        )
    account, agency_name = row
    if current_user.role == UserRole.SUPER_ADMIN:
        return account, agency_name
    if account.agency_id != current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account is outside your management scope"
        )
    if current_user.role == UserRole.AGENCY_ADMIN and account.role in {
        UserRole.AGENCY_STAFF.value,
        UserRole.AGENCY_COORDINATOR.value,
    }:
        return account, agency_name
    if current_user.role == UserRole.AGENCY_MANAGER and account.role in {
        UserRole.AGENCY_STAFF.value,
        UserRole.AGENCY_COORDINATOR.value,
    }:
        return account, agency_name
    if current_user.role == UserRole.AGENCY_MANAGER and account.id == current_user.id:
        return account, agency_name
    if current_user.role == UserRole.AGENCY_ADMIN and account.role == UserRole.AGENCY_MANAGER.value:
        return account, agency_name
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account is outside your management scope"
        )


async def _deactivate_coordinator_assignments(session: AsyncSession, account: UserModel) -> None:
    if account.role != UserRole.AGENCY_COORDINATOR.value:
        return
    active_group_ids = list(
        (
            await session.execute(
                select(CoordinatorGroupAssignmentModel.group_id).where(
                    CoordinatorGroupAssignmentModel.coordinator_user_id == account.id,
                    CoordinatorGroupAssignmentModel.active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    if active_group_ids:
        # Manager close and assignment replacement use the group row as their
        # participant-set mutex. Lock every affected group deterministically
        # before changing active assignment membership.
        await session.execute(
            select(ClientGroupModel.id)
            .where(ClientGroupModel.id.in_(sorted(set(active_group_ids), key=str)))
            .order_by(ClientGroupModel.id.asc())
            .with_for_update(of=ClientGroupModel)
        )
    now = datetime.now(tz=UTC)
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


async def _fence_dashboard_sessions(session: AsyncSession, account: UserModel) -> None:
    """Invalidate both refresh tokens and already-issued access JWTs."""

    repository = IdentitySecurityRepository(session)
    security_state = await repository.get_state(account.id, lock=True)
    if security_state is None:
        security_state = await repository.ensure_state(account)
    security_state.session_version += 1
    security_state.updated_at = datetime.now(tz=UTC)
    await RefreshTokenRepository(session).revoke_all_for_user(account.id)
    await _fence_coordinator_mobile_sessions(
        session,
        account,
        reason="account_session_fenced",
    )


async def _fence_coordinator_mobile_sessions(
    session: AsyncSession,
    account: UserModel,
    *,
    reason: str,
) -> None:
    if (
        account.role != UserRole.AGENCY_COORDINATOR.value
        or account.agency_id is None
    ):
        return
    await revoke_user_mobile_sessions(
        session,
        agency_id=account.agency_id,
        user_id=account.id,
        subject_role="coordinator",
        reason=reason,
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
        ip_address=trusted_client_ip(request),
        metadata={"target_role": account.role, "target_email": account.email, **(metadata or {})},
    )


def _account_response(
    account: UserModel,
    agency_name: str | None,
    security_state: UserSecurityStateModel | None = None,
    *,
    activation_token: str | None = None,
) -> ManagedAccountResponse:
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
        credential_state=(
            _validated_credential_state(security_state.credential_state)
            if security_state
            else "active"
        ),
        activation_token=activation_token,
    )
