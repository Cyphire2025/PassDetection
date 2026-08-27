"""
Admin Routes
============
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from app.application.platform_policies import PLATFORM_SETTINGS_KEY, PlatformPolicies
from app.application.security.destructive_mutation_policy import (
    DestructiveMutationPolicy,
    DestructiveOwnedGroupsMutation,
    record_destructive_failure,
)
from app.core.logging.logger import get_logger
from app.core.security.password import hash_password
from app.domain.entities.entities import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
    PENDING_REVIEW_PASSPORT_STATUS_VALUES,
    GroupStatus,
    PassportProcessingStatus,
    User,
    UserRole,
)
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.infrastructure.database.email_models import EmailConnectionModel
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    ManagerGroupAccessModel,
    NotificationModel,
    PassportProcessingJobModel,
    PassportSubmissionModel,
    PlatformSettingModel,
    PlatformSettingsValue,
    StorageCleanupJobModel,
    UserModel,
    UserSecurityStateModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppBroadcastRejectedContactModel,
    WhatsAppBroadcastSupportContactModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.storage_cleanup import (
    process_storage_cleanup_job,
    stage_storage_cleanup_jobs,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.identity_security_repository import IdentitySecurityRepository
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
)
from app.infrastructure.storage.passport_object_keys import passport_storage_keys
from app.presentation.api.v1.schemas.operations_schemas import (
    AdminOverviewResponse,
    AssignManagerGroupsRequest,
    CreateManagerRequest,
    DeleteManagerRequest,
    DeleteManagerResponse,
    ManagerGroupAccessResponse,
    ManagerResponse,
    PassportRetentionControlRequest,
    PassportRetentionControlResponse,
    PlatformSettingsResponse,
    PurgePassportDataResponse,
    UpdatePlatformSettingsRequest,
)
from app.presentation.dependencies.auth import require_recent_mfa, require_role
from app.presentation.dependencies.csrf import require_cookie_csrf
from app.presentation.security.client_ip import trusted_client_ip

router = APIRouter()
logger = get_logger(__name__)
DEFAULT_PLATFORM_SETTINGS = PlatformPolicies().as_dict()
REMOVED_GROUP_STATUSES = (GroupStatus.ARCHIVED.value, GroupStatus.DELETED.value)
PASSPORT_PURGE_INLINE_CLEANUP_MAX_OBJECTS = 500
PLATFORM_SETTINGS_REVISION_CONFLICT = "PLATFORM_SETTINGS_REVISION_CONFLICT"

_CredentialState = Literal["invited", "active"]


def _validated_credential_state(value: str) -> _CredentialState:
    if value not in {"invited", "active"}:
        raise RuntimeError("Invalid persisted workforce credential state.")
    return cast(_CredentialState, value)


@dataclass(frozen=True, slots=True)
class _WhatsAppPurgeCounts:
    broadcast_groups: int
    recipients: int
    rejected_contacts: int
    support_contacts: int
    message_logs: int
    delivery_states: int


@dataclass(frozen=True, slots=True)
class _PreviousManagerDelete:
    response: DeleteManagerResponse
    agency_id: uuid.UUID | None


def _manager_scope(current_user: User) -> list[ColumnElement[bool]]:
    if current_user.role == UserRole.SUPER_ADMIN:
        return [
            UserModel.role == UserRole.AGENCY_MANAGER.value,
            UserModel.deleted_at.is_(None),
        ]
    return [
        UserModel.role == UserRole.AGENCY_MANAGER.value,
        UserModel.agency_id == current_user.agency_id,
        UserModel.deleted_at.is_(None),
    ]


def _staff_scope(current_user: User) -> list[ColumnElement[bool]]:
    if current_user.role == UserRole.SUPER_ADMIN:
        return [
            UserModel.role == UserRole.AGENCY_STAFF.value,
            UserModel.deleted_at.is_(None),
        ]
    return [
        UserModel.role == UserRole.AGENCY_STAFF.value,
        UserModel.agency_id == current_user.agency_id,
        UserModel.deleted_at.is_(None),
    ]


@router.get(
    "/overview",
    response_model=AdminOverviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Get administrative platform overview",
)
async def get_admin_overview(
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> AdminOverviewResponse:
    agency_filter = [] if current_user.role == UserRole.SUPER_ADMIN else [AgencyModel.id == current_user.agency_id]
    user_filter = [] if current_user.role == UserRole.SUPER_ADMIN else [UserModel.agency_id == current_user.agency_id]
    group_filter = [] if current_user.role == UserRole.SUPER_ADMIN else [ClientGroupModel.agency_id == current_user.agency_id]
    passport_scope_filter = []
    if current_user.role != UserRole.SUPER_ADMIN:
        passport_scope_filter.append(PassportSubmissionModel.agency_id == current_user.agency_id)

    agencies = await _count(session, select(func.count()).select_from(AgencyModel).where(*agency_filter))
    users = await _count(session, select(func.count()).select_from(UserModel).where(*user_filter))
    groups = await _count(session, select(func.count()).select_from(ClientGroupModel).where(*group_filter))
    passports = await _count(
        session,
        select(func.count()).select_from(PassportSubmissionModel).where(
            *passport_scope_filter,
            PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
        ),
    )
    pending = await _count(
        session,
        select(func.count()).select_from(PassportSubmissionModel).join(
            ClientGroupModel,
            PassportSubmissionModel.group_id == ClientGroupModel.id,
        ).where(
            *passport_scope_filter,
            PassportSubmissionModel.status.in_(PENDING_REVIEW_PASSPORT_STATUS_VALUES),
            ClientGroupModel.status.notin_(["archived", "deleted"]),
        ),
    )
    submitted = await _count(
        session,
        select(func.count()).select_from(PassportSubmissionModel).join(
            ClientGroupModel,
            PassportSubmissionModel.group_id == ClientGroupModel.id,
        ).where(
            *passport_scope_filter,
            PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
            ClientGroupModel.status.notin_(["archived", "deleted"]),
        ),
    )
    failed = await _count(
        session,
        select(func.count()).select_from(PassportSubmissionModel).join(
            ClientGroupModel,
            PassportSubmissionModel.group_id == ClientGroupModel.id,
        ).where(
            *passport_scope_filter,
            PassportSubmissionModel.status == PassportProcessingStatus.FAILED.value,
            ClientGroupModel.status.notin_(["archived", "deleted"]),
        ),
    )
    return AdminOverviewResponse(
        agencies=agencies,
        users=users,
        client_groups=groups,
        passport_submissions=passports,
        pending_review=pending,
        client_submitted=submitted,
        failed=failed,
    )


@router.get(
    "/managers",
    response_model=list[ManagerResponse],
    status_code=status.HTTP_200_OK,
    summary="List manager accounts",
)
async def list_managers(
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
    skip: int = 0,
    limit: int = 100,
) -> list[ManagerResponse]:
    stmt = (
        select(UserModel)
        .where(*_manager_scope(current_user))
        .order_by(UserModel.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(stmt)
    managers = list(result.scalars().all())
    if not managers:
        return []

    manager_ids = [user.id for user in managers]
    groups_result = await session.execute(
        select(ClientGroupModel).where(
            ClientGroupModel.agency_id.in_([user.agency_id for user in managers if user.agency_id]),
            or_(
                ClientGroupModel.created_by_user_id.in_(manager_ids),
                ClientGroupModel.id.in_(
                    select(ManagerGroupAccessModel.group_id).where(
                        ManagerGroupAccessModel.manager_id.in_(manager_ids)
                    )
                ),
            ),
        )
    )
    groups = list(groups_result.scalars().all())
    access_result = await session.execute(
        select(ManagerGroupAccessModel).where(ManagerGroupAccessModel.manager_id.in_(manager_ids))
    )
    access_rows = list(access_result.scalars().all())
    security_result = await session.execute(
        select(UserSecurityStateModel).where(
            UserSecurityStateModel.user_id.in_(manager_ids)
        )
    )
    security_by_user_id = {
        state.user_id: state for state in security_result.scalars().all()
    }

    return [
        ManagerResponse(
            id=user.id,
            full_name=user.full_name,
            email=user.email,
            role=user.role,
            agency_id=user.agency_id,
            is_active=user.is_active,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
            created_groups=[
                _group_response(group)
                for group in groups
                if group.created_by_user_id == user.id
            ],
            assigned_groups=[
                _group_response(group)
                for access in access_rows
                for group in groups
                if access.manager_id == user.id and access.group_id == group.id
            ],
            credential_state=(
                _validated_credential_state(
                    security_by_user_id[user.id].credential_state
                )
                if user.id in security_by_user_id
                else "active"
            ),
        )
        for user in managers
    ]


@router.post(
    "/managers",
    response_model=ManagerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a limited manager account",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def create_manager(
    body: CreateManagerRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> ManagerResponse:
    if not current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Assign the admin to an agency before creating managers")

    existing = await session.execute(select(UserModel).where(UserModel.email == str(body.email).lower().strip()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists")

    manager = UserModel(
        email=str(body.email).lower().strip(),
        hashed_password=hash_password(f"Inv1{secrets.token_urlsafe(32)}"),
        full_name=body.full_name.strip(),
        role=UserRole.AGENCY_MANAGER.value,
        agency_id=current_user.agency_id,
        is_active=True,
    )
    session.add(manager)
    await session.flush()
    identity_repository = IdentitySecurityRepository(session)
    security_state = UserSecurityStateModel(
        user_id=manager.id,
        credential_state="invited",
        session_version=1,
        mfa_required=True,
    )
    session.add(security_state)
    _, activation_token = await identity_repository.issue_action_token(
        user_id=manager.id,
        purpose="activation",
        expires_in=timedelta(days=7),
        created_by_user_id=current_user.id,
    )
    await AuditLogRepository(session).record(
        action="manager.invited",
        entity_type="user_account",
        entity_id=str(manager.id),
        agency_id=manager.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=trusted_client_ip(request),
        metadata={"target_role": manager.role, "target_email": manager.email},
    )
    response.headers["Cache-Control"] = "private, no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"

    return ManagerResponse(
        id=manager.id,
        full_name=manager.full_name,
        email=manager.email,
        role=manager.role,
        agency_id=manager.agency_id,
        is_active=manager.is_active,
        created_at=manager.created_at,
        last_login_at=manager.last_login_at,
        credential_state=_validated_credential_state(security_state.credential_state),
        activation_token=activation_token,
    )


@router.get(
    "/settings",
    response_model=PlatformSettingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get editable platform settings",
)
async def get_platform_settings(
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> PlatformSettingsResponse:
    settings = await _load_platform_settings(session)
    return settings


@router.put(
    "/settings",
    response_model=PlatformSettingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Update editable platform settings",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def update_platform_settings(
    body: UpdatePlatformSettingsRequest,
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> PlatformSettingsResponse:
    result = await session.execute(
        select(PlatformSettingModel)
        .where(PlatformSettingModel.key == PLATFORM_SETTINGS_KEY)
        .with_for_update()
    )
    row = result.scalar_one_or_none()
    if row is None:
        if body.expected_updated_at is not None:
            raise _platform_settings_revision_conflict(current_updated_at=None)
    elif body.expected_updated_at is None or not _same_platform_settings_revision(
        row.updated_at,
        body.expected_updated_at,
    ):
        raise _platform_settings_revision_conflict(current_updated_at=row.updated_at)

    value = PlatformSettingsValue(
        platform_name=body.platform_name,
        require_client_email=body.require_client_email,
        require_client_phone=body.require_client_phone,
        duplicate_contact_policy=body.duplicate_contact_policy,
        default_group_status=body.default_group_status,
        auto_archive_closed_groups_days=body.auto_archive_closed_groups_days,
        passport_data_retention_days=body.passport_data_retention_days,
        mrz_review_threshold=body.mrz_review_threshold,
        allow_manager_group_creation=body.allow_manager_group_creation,
        audit_log_retention_days=body.audit_log_retention_days,
    )
    if row:
        row.value = value
    else:
        row = PlatformSettingModel(key=PLATFORM_SETTINGS_KEY, value=value)
        session.add(row)
    await session.flush()
    await session.refresh(row)

    await AuditLogRepository(session).record(
        action="platform_settings_updated",
        entity_type="platform_settings",
        agency_id=None if current_user.role == UserRole.SUPER_ADMIN else current_user.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=PLATFORM_SETTINGS_KEY,
        metadata=dict(value),
    )
    return PlatformSettingsResponse(**row.value, updated_at=row.updated_at)


def _same_platform_settings_revision(current: datetime, expected: datetime) -> bool:
    """Compare exact instants without tolerances or string-format ambiguity."""

    normalized_current = (
        current.replace(tzinfo=UTC) if current.utcoffset() is None else current.astimezone(UTC)
    )
    return normalized_current == expected.astimezone(UTC)


def _platform_settings_revision_conflict(
    *,
    current_updated_at: datetime | None,
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": PLATFORM_SETTINGS_REVISION_CONFLICT,
            "message": "Platform settings changed. Reload the latest values before saving.",
            "current_updated_at": (
                current_updated_at.isoformat() if current_updated_at is not None else None
            ),
        },
    )


@router.get(
    "/groups/{group_id}/passport-retention",
    response_model=PassportRetentionControlResponse,
    status_code=status.HTTP_200_OK,
    summary="Inspect an explicit group passport-retention schedule",
)
async def get_group_passport_retention(
    group_id: uuid.UUID,
    current_user: User = Depends(
        require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])
    ),
    session: AsyncSession = Depends(get_db_session),
) -> PassportRetentionControlResponse:
    group = await _load_retention_control_group(
        session,
        group_id=group_id,
        current_user=current_user,
        lock=False,
    )
    return _passport_retention_response(group)


@router.put(
    "/groups/{group_id}/passport-retention",
    response_model=PassportRetentionControlResponse,
    status_code=status.HTTP_200_OK,
    summary="Place or release a legal hold on group passport data",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def update_group_passport_retention(
    group_id: uuid.UUID,
    body: PassportRetentionControlRequest,
    current_user: User = Depends(
        require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])
    ),
    session: AsyncSession = Depends(get_db_session),
) -> PassportRetentionControlResponse:
    group = await _load_retention_control_group(
        session,
        group_id=group_id,
        current_user=current_user,
        lock=True,
    )
    now = datetime.now(tz=UTC)
    previous_hold = group.passport_legal_hold
    if body.legal_hold:
        group.passport_legal_hold = True
        group.passport_legal_hold_reason = body.reason
        group.passport_legal_hold_set_at = now
        group.passport_legal_hold_set_by_user_id = current_user.id
    else:
        group.passport_legal_hold = False
        group.passport_legal_hold_reason = None
        group.passport_legal_hold_set_at = None
        group.passport_legal_hold_set_by_user_id = None

    policies = PlatformPolicies.from_mapping(
        (await _load_platform_settings(session)).model_dump(exclude={"updated_at"})
    )
    anchor = group.deleted_at or group.closed_at
    if anchor is not None and (
        group.passport_purge_at is None
        or group.passport_retention_days_applied
        != policies.passport_data_retention_days
    ):
        group.passport_retention_days_applied = policies.passport_data_retention_days
        group.passport_purge_at = anchor + timedelta(
            days=policies.passport_data_retention_days
        )

    await AuditLogRepository(session).record(
        action=(
            "passport_legal_hold_placed"
            if body.legal_hold
            else "passport_legal_hold_released"
        ),
        entity_type="client_group",
        entity_id=str(group.id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "reason": body.reason,
            "previous_legal_hold": previous_hold,
            "passport_purge_at": (
                group.passport_purge_at.isoformat()
                if group.passport_purge_at is not None
                else None
            ),
            "passport_retention_days_applied": (
                group.passport_retention_days_applied
            ),
        },
    )
    await session.flush()
    return _passport_retention_response(group)


@router.get(
    "/groups",
    response_model=list[ManagerGroupAccessResponse],
    status_code=status.HTTP_200_OK,
    summary="List groups available for account access assignment",
)
async def list_admin_groups(
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER])),
    session: AsyncSession = Depends(get_db_session),
) -> list[ManagerGroupAccessResponse]:
    filters: list[ColumnElement[bool]] = [
        ClientGroupModel.status.notin_(REMOVED_GROUP_STATUSES)
    ]
    if current_user.role != UserRole.SUPER_ADMIN:
        filters.append(ClientGroupModel.agency_id == current_user.agency_id)
    result = await session.execute(
        select(ClientGroupModel)
        .where(*filters)
        .order_by(ClientGroupModel.created_at.desc())
    )
    return [_group_response(group) for group in result.scalars().all()]


@router.get(
    "/staff",
    response_model=list[ManagerResponse],
    status_code=status.HTTP_200_OK,
    summary="List staff accounts with group access",
)
async def list_staff_for_access(
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER])),
    session: AsyncSession = Depends(get_db_session),
) -> list[ManagerResponse]:
    result = await session.execute(
        select(UserModel).where(*_staff_scope(current_user)).order_by(UserModel.created_at.desc())
    )
    return [await _manager_response(session, staff) for staff in result.scalars().all()]


@router.put(
    "/staff/{staff_id}/groups",
    response_model=ManagerResponse,
    status_code=status.HTTP_200_OK,
    summary="Replace a staff member's assigned group access",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def assign_staff_groups(
    staff_id: uuid.UUID,
    body: AssignManagerGroupsRequest,
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN, UserRole.AGENCY_MANAGER])),
    session: AsyncSession = Depends(get_db_session),
) -> ManagerResponse:
    staff_result = await session.execute(select(UserModel).where(UserModel.id == staff_id, *_staff_scope(current_user)))
    staff = staff_result.scalar_one_or_none()
    if not staff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Staff account was not found")
    if not staff.agency_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Staff account is not assigned to an agency")

    group_ids = list(dict.fromkeys(body.group_ids))
    if group_ids:
        groups_result = await session.execute(
            select(ClientGroupModel).where(
                ClientGroupModel.id.in_(group_ids),
                ClientGroupModel.agency_id == staff.agency_id,
                ClientGroupModel.status.notin_(REMOVED_GROUP_STATUSES),
            )
        )
        valid_groups = list(groups_result.scalars().all())
        valid_group_ids = {group.id for group in valid_groups}
        if valid_group_ids != set(group_ids):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more groups are not assignable to this staff member")
        group_ids = [group_id for group_id in group_ids if not any(group.id == group_id and group.created_by_user_id == staff.id for group in valid_groups)]

    await session.execute(delete(ManagerGroupAccessModel).where(ManagerGroupAccessModel.manager_id == staff.id))
    for group_id in group_ids:
        session.add(
            ManagerGroupAccessModel(
                manager_id=staff.id,
                group_id=group_id,
                agency_id=staff.agency_id,
            )
        )
    await session.flush()
    return await _manager_response(session, staff)


@router.put(
    "/managers/{manager_id}/groups",
    response_model=ManagerResponse,
    status_code=status.HTTP_200_OK,
    summary="Replace a manager's extra assigned group access",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def assign_manager_groups(
    manager_id: uuid.UUID,
    body: AssignManagerGroupsRequest,
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> ManagerResponse:
    manager_result = await session.execute(select(UserModel).where(UserModel.id == manager_id, *_manager_scope(current_user)))
    manager = manager_result.scalar_one_or_none()
    if not manager:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager was not found")
    if not manager.agency_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Manager is not assigned to an agency")

    group_ids = list(dict.fromkeys(body.group_ids))
    if group_ids:
        groups_result = await session.execute(
            select(ClientGroupModel).where(
                ClientGroupModel.id.in_(group_ids),
                ClientGroupModel.agency_id == manager.agency_id,
                ClientGroupModel.status.notin_(REMOVED_GROUP_STATUSES),
            )
        )
        valid_groups = list(groups_result.scalars().all())
        valid_group_ids = {group.id for group in valid_groups}
        if valid_group_ids != set(group_ids):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more groups are not assignable to this manager")
        group_ids = [group_id for group_id in group_ids if not any(group.id == group_id and group.created_by_user_id == manager.id for group in valid_groups)]

    await session.execute(delete(ManagerGroupAccessModel).where(ManagerGroupAccessModel.manager_id == manager.id))
    for group_id in group_ids:
        session.add(
            ManagerGroupAccessModel(
                manager_id=manager.id,
                group_id=group_id,
                agency_id=manager.agency_id,
            )
        )
    await session.flush()
    return await _manager_response(session, manager)


@router.delete(
    "/managers/{manager_id}",
    response_model=DeleteManagerResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete a manager account",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def delete_manager(
    manager_id: uuid.UUID,
    body: DeleteManagerRequest | None = None,
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> DeleteManagerResponse:
    delete_owned_data = bool(body and body.delete_owned_data)
    manager_result = await session.execute(
        select(UserModel)
        .where(UserModel.id == manager_id, *_manager_scope(current_user))
        .with_for_update()
    )
    manager = manager_result.scalar_one_or_none()
    if not manager:
        previous = await _previous_manager_delete_result(
            session,
            manager_id=manager_id,
            delete_owned_data=delete_owned_data,
        )
        if previous is not None:
            await AuditLogRepository(session).record(
                action="manager_delete_idempotent_replay",
                entity_type="user",
                entity_id=str(manager_id),
                agency_id=previous.agency_id,
                user_id=current_user.id,
                actor_email=current_user.email,
                metadata={
                    "delete_owned_data": delete_owned_data,
                    "result": "idempotent_replay",
                },
            )
            await session.commit()
            return previous.response
        raise EntityNotFoundError("Manager", manager_id)

    email_connection_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(EmailConnectionModel)
                .where(EmailConnectionModel.owner_user_id == manager.id)
            )
        ).scalar_one()
    )
    cleanup_jobs: tuple[StorageCleanupJobModel, ...] = ()
    owned_data_mutation: DestructiveOwnedGroupsMutation | None = None
    response = DeleteManagerResponse(
        deleted_manager_id=manager.id,
        deleted_owned_data=delete_owned_data,
    )

    if delete_owned_data:
        owned_data_mutation = (
            await DestructiveMutationPolicy(session).require_manager_owned_groups(
                user=current_user,
                manager_id=manager.id,
                manager_agency_id=manager.agency_id,
                action="manager_owned_passport_data_delete",
            )
        )
        group_ids = [group.id for group in owned_data_mutation.groups]

        submission_rows = await session.execute(
            select(
                PassportSubmissionModel.id,
                PassportSubmissionModel.image_s3_key,
                PassportSubmissionModel.thumbnail_s3_key,
                PassportSubmissionModel.passport_back_s3_key,
                PassportSubmissionModel.passport_photo_s3_key,
            )
            .where(
                PassportSubmissionModel.group_id.in_(group_ids),
                PassportSubmissionModel.agency_id == manager.agency_id,
            )
            .with_for_update()
        ) if group_ids else None
        submissions = list(submission_rows.all()) if submission_rows else []
        submission_ids = [row.id for row in submissions]
        storage_keys = passport_storage_keys(submissions)
        crop_repository = PassportImageCropRepository(session)
        storage_keys.extend(await crop_repository.derived_storage_keys(submission_ids))
        storage_keys.extend(await crop_repository.edit_storage_keys(submission_ids))

        cleanup_jobs = stage_storage_cleanup_jobs(
            session,
            agency_id=manager.agency_id,
            source="passport_submission_delete",
            context_id=(
                f"manager:{manager.id}:{owned_data_mutation.request_fingerprint}"
            ),
            storage_keys=storage_keys,
        )
        group_entity_ids = [str(group_id) for group_id in group_ids]
        submission_entity_ids = [str(submission_id) for submission_id in submission_ids]
        response.deleted_notifications = await _delete_entity_rows(
            session,
            NotificationModel,
            agency_id=manager.agency_id,
            group_entity_ids=group_entity_ids,
            submission_entity_ids=submission_entity_ids,
        )
        response.deleted_processing_jobs = await _delete_by_ids(
            session,
            PassportProcessingJobModel,
            PassportProcessingJobModel.submission_id,
            submission_ids,
        )
        response.deleted_passport_submissions = await _delete_by_ids(
            session,
            PassportSubmissionModel,
            PassportSubmissionModel.id,
            submission_ids,
        )
        response.deleted_client_groups = await _delete_by_ids(session, ClientGroupModel, ClientGroupModel.id, group_ids)

    await AuditLogRepository(session).record(
        action="manager_deleted",
        entity_type="user",
        entity_id=str(manager.id),
        agency_id=manager.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "delete_owned_data": delete_owned_data,
            "storage_cleanup_job_count": len(cleanup_jobs),
            **response.model_dump(mode="json"),
        },
    )
    if email_connection_count:
        now = datetime.now(tz=UTC)
        await session.execute(
            update(EmailConnectionModel)
            .where(EmailConnectionModel.owner_user_id == manager.id)
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
        manager.is_active = False
        manager.email = f"deleted-{manager.id}@deleted.invalid"
        manager.hashed_password = hash_password(secrets.token_urlsafe(48))
        manager.deleted_at = now
        manager.updated_at = now
    else:
        await session.delete(manager)
    await session.flush()
    # The manager, owned passport rows, and encrypted object-cleanup tombstones
    # become durable together. Object storage is never touched before this
    # commit succeeds.
    try:
        await session.commit()
    except Exception as exc:
        if owned_data_mutation is not None:
            await record_destructive_failure(
                owned_data_mutation,
                user=current_user,
                error=exc,
            )
        raise

    for cleanup_job in cleanup_jobs:
        try:
            cleanup_result = await process_storage_cleanup_job(cleanup_job.id)
            if cleanup_result is None or not cleanup_result.completed:
                logger.warning(
                    "manager_passport_storage_cleanup_deferred",
                    manager_id=str(manager_id),
                    cleanup_job_id=str(cleanup_job.id),
                    object_count=cleanup_job.object_count,
                    error_type=None,
                )
                continue
            response.deleted_storage_objects += cleanup_result.deleted_count
        except Exception as exc:
            logger.warning(
                "manager_passport_storage_cleanup_deferred",
                manager_id=str(manager_id),
                cleanup_job_id=str(cleanup_job.id),
                object_count=cleanup_job.object_count,
                error_type=type(exc).__name__,
            )
    return response


@router.delete(
    "/passport-data",
    response_model=PurgePassportDataResponse,
    status_code=status.HTTP_200_OK,
    summary="Permanently delete passport and WhatsApp broadcast data",
    dependencies=[Depends(require_cookie_csrf), Depends(require_recent_mfa)],
)
async def purge_passport_data(
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> PurgePassportDataResponse:
    if current_user.role != UserRole.SUPER_ADMIN and not current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This admin account is not assigned to an agency")

    whatsapp_group_lock = select(WhatsAppBroadcastGroupModel.id).order_by(
        WhatsAppBroadcastGroupModel.id
    )
    if current_user.role != UserRole.SUPER_ADMIN:
        whatsapp_group_lock = whatsapp_group_lock.where(
            WhatsAppBroadcastGroupModel.agency_id == current_user.agency_id
        )
    await session.execute(whatsapp_group_lock.with_for_update())
    processing_filter = [
        WhatsAppRecipientMessageStateModel.status == "processing"
    ]
    if current_user.role != UserRole.SUPER_ADMIN:
        processing_filter.append(
            WhatsAppRecipientMessageStateModel.agency_id == current_user.agency_id
        )
    processing_result = await session.execute(
        select(func.count())
        .select_from(WhatsAppRecipientMessageStateModel)
        .where(*processing_filter)
    )
    if int(processing_result.scalar_one()) > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A WhatsApp provider request is currently in progress. "
                "Wait for it to finish before deleting all data."
            ),
        )

    # Legal-hold changes and every other destructive group mutation lock these
    # same rows. The ordered scope lock makes the hold check and the ensuing
    # purge one serialized decision rather than a count-then-delete race.
    mutation = await DestructiveMutationPolicy(session).require_scoped_groups(
        user=current_user,
        action="passport_data_purge",
    )
    group_ids = [group.id for group in mutation.groups]
    # Even a platform purge is bounded to the rows in the locked group set.
    # A group inserted concurrently after the scope lock is therefore left
    # wholly intact instead of losing submissions while its group row survives.
    passport_filter = [PassportSubmissionModel.group_id.in_(group_ids)]

    submission_rows = await session.execute(
        select(
            PassportSubmissionModel.id,
            PassportSubmissionModel.image_s3_key,
            PassportSubmissionModel.thumbnail_s3_key,
            PassportSubmissionModel.passport_back_s3_key,
            PassportSubmissionModel.passport_photo_s3_key,
        )
        .where(*passport_filter)
        .order_by(PassportSubmissionModel.id)
        .with_for_update()
    )
    submissions = list(submission_rows.all())
    submission_ids = [row.id for row in submissions]
    storage_keys = passport_storage_keys(submissions)
    crop_repository = PassportImageCropRepository(session)
    storage_keys.extend(await crop_repository.derived_storage_keys(submission_ids))
    storage_keys.extend(await crop_repository.edit_storage_keys(submission_ids))

    # The encrypted cleanup rows are committed atomically with the authoritative
    # database deletion. Object storage is deliberately untouched until after
    # that commit, so neither a storage failure nor a database rollback can
    # leave retained rows pointing at files that have already disappeared.
    cleanup_jobs = stage_storage_cleanup_jobs(
        session,
        agency_id=(
            None
            if current_user.role == UserRole.SUPER_ADMIN
            else current_user.agency_id
        ),
        source="passport_submission_delete",
        context_id=(
            "platform"
            if current_user.role == UserRole.SUPER_ADMIN
            else f"agency:{current_user.agency_id}"
        ),
        storage_keys=storage_keys,
    )

    group_entity_ids = [str(group_id) for group_id in group_ids]
    submission_entity_ids = [str(submission_id) for submission_id in submission_ids]

    deleted_notifications = await _delete_entity_rows(
        session,
        NotificationModel,
        agency_id=None if current_user.role == UserRole.SUPER_ADMIN else current_user.agency_id,
        group_entity_ids=group_entity_ids,
        submission_entity_ids=submission_entity_ids,
    )
    # Security audit history is append-only application evidence and has its
    # own bounded retention/export lifecycle; a data purge must not erase it.
    deleted_audit_logs = 0

    deleted_processing_jobs = await _delete_by_ids(
        session,
        PassportProcessingJobModel,
        PassportProcessingJobModel.submission_id,
        submission_ids,
    )
    deleted_passport_submissions = await _delete_by_ids(
        session,
        PassportSubmissionModel,
        PassportSubmissionModel.id,
        submission_ids,
    )
    deleted_client_groups = await _delete_by_ids(session, ClientGroupModel, ClientGroupModel.id, group_ids)
    whatsapp_counts = await _delete_whatsapp_broadcast_data(
        session,
        agency_id=None if current_user.role == UserRole.SUPER_ADMIN else current_user.agency_id,
    )

    response = PurgePassportDataResponse(
        deleted_client_groups=deleted_client_groups,
        deleted_passport_submissions=deleted_passport_submissions,
        deleted_processing_jobs=deleted_processing_jobs,
        deleted_notifications=deleted_notifications,
        deleted_audit_logs=deleted_audit_logs,
        deleted_storage_objects=0,
        deleted_whatsapp_broadcast_groups=whatsapp_counts.broadcast_groups,
        deleted_whatsapp_recipients=whatsapp_counts.recipients,
        deleted_whatsapp_rejected_contacts=whatsapp_counts.rejected_contacts,
        deleted_whatsapp_support_contacts=whatsapp_counts.support_contacts,
        deleted_whatsapp_message_logs=whatsapp_counts.message_logs,
        deleted_whatsapp_delivery_states=whatsapp_counts.delivery_states,
        storage_cleanup_deferred=bool(cleanup_jobs),
    )

    await AuditLogRepository(session).record(
        action="passport_data_purged",
        entity_type="platform" if current_user.role == UserRole.SUPER_ADMIN else "agency",
        agency_id=None if current_user.role == UserRole.SUPER_ADMIN else current_user.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=None if current_user.role == UserRole.SUPER_ADMIN else str(current_user.agency_id),
        metadata={
            **response.model_dump(),
            "storage_objects_scheduled_for_cleanup": len(storage_keys),
            "storage_cleanup_job_count": len(cleanup_jobs),
            "request_fingerprint": mutation.request_fingerprint,
        },
        result="success",
    )

    # This explicit boundary is required because the FastAPI session dependency
    # otherwise commits only after the route returns. Cleanup may begin only
    # after the tombstones, row deletion, and audit event are durable together.
    try:
        await session.commit()
    except Exception as exc:
        await record_destructive_failure(
            mutation,
            user=current_user,
            error=exc,
        )
        raise

    cleanup_object_count = sum(job.object_count for job in cleanup_jobs)
    cleanup_deferred = (
        cleanup_object_count > PASSPORT_PURGE_INLINE_CLEANUP_MAX_OBJECTS
    )
    deleted_storage_objects = 0
    if not cleanup_deferred:
        for cleanup_job in cleanup_jobs:
            try:
                cleanup_result = await process_storage_cleanup_job(cleanup_job.id)
                if cleanup_result is None or not cleanup_result.completed:
                    cleanup_deferred = True
                    continue
                deleted_storage_objects += cleanup_result.deleted_count
            except Exception as exc:
                # The periodic lease-safe worker retries the already-committed
                # job; do not turn a completed database purge into an unsafe
                # compensating rollback.
                cleanup_deferred = True
                logger.warning(
                    "admin_passport_purge_storage_cleanup_deferred",
                    cleanup_job_id=str(cleanup_job.id),
                    object_count=cleanup_job.object_count,
                    error_type=type(exc).__name__,
                )

    response.deleted_storage_objects = deleted_storage_objects
    response.storage_cleanup_deferred = cleanup_deferred
    return response


async def _count(session: AsyncSession, stmt) -> int:  # type: ignore[no-untyped-def]
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def _previous_manager_delete_result(
    session: AsyncSession,
    *,
    manager_id: uuid.UUID,
    delete_owned_data: bool,
) -> _PreviousManagerDelete | None:
    """Return an exact committed manager-deletion replay, if one exists."""

    result = await session.execute(
        select(AuditLogModel)
        .where(
            AuditLogModel.action == "manager_deleted",
            AuditLogModel.entity_type == "user",
            AuditLogModel.entity_id == str(manager_id),
            AuditLogModel.metadata_json["delete_owned_data"].as_boolean()
            == delete_owned_data,
        )
        .order_by(AuditLogModel.created_at.desc(), AuditLogModel.id.desc())
        .limit(1)
    )
    audit = result.scalar_one_or_none()
    if audit is None:
        return None
    metadata = audit.metadata_json or {}
    try:
        response = DeleteManagerResponse.model_validate(metadata)
    except ValueError:
        return None
    if response.deleted_manager_id != manager_id:
        return None
    # Immediate cleanup counts are not authoritative on a later replay. The
    # committed tombstones remain the durable source of truth for object work.
    response.deleted_storage_objects = 0
    return _PreviousManagerDelete(response=response, agency_id=audit.agency_id)


async def _load_platform_settings(session: AsyncSession) -> PlatformSettingsResponse:
    result = await session.execute(select(PlatformSettingModel).where(PlatformSettingModel.key == PLATFORM_SETTINGS_KEY))
    row = result.scalar_one_or_none()
    if not row:
        return PlatformSettingsResponse(**DEFAULT_PLATFORM_SETTINGS)
    return PlatformSettingsResponse(**{**DEFAULT_PLATFORM_SETTINGS, **row.value}, updated_at=row.updated_at)


async def _load_retention_control_group(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    current_user: User,
    lock: bool,
) -> ClientGroupModel:
    statement = select(ClientGroupModel).where(ClientGroupModel.id == group_id)
    if current_user.role != UserRole.SUPER_ADMIN:
        statement = statement.where(
            ClientGroupModel.agency_id == current_user.agency_id
        )
    if lock:
        statement = statement.with_for_update()
    result = await session.execute(statement)
    group = result.scalar_one_or_none()
    if group is None:
        # Keep cross-tenant existence confidential.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client group was not found",
        )
    return group


def _passport_retention_response(
    group: ClientGroupModel,
) -> PassportRetentionControlResponse:
    return PassportRetentionControlResponse(
        group_id=group.id,
        passport_purge_at=group.passport_purge_at,
        passport_retention_days_applied=group.passport_retention_days_applied,
        legal_hold=group.passport_legal_hold,
        legal_hold_reason=group.passport_legal_hold_reason,
        legal_hold_set_at=group.passport_legal_hold_set_at,
        legal_hold_set_by_user_id=group.passport_legal_hold_set_by_user_id,
    )


def _group_response(group: ClientGroupModel) -> ManagerGroupAccessResponse:
    return ManagerGroupAccessResponse(
        id=group.id,
        agency_id=group.agency_id,
        name=group.name,
        status=group.status,
        created_by_user_id=group.created_by_user_id,
    )


async def _manager_response(session: AsyncSession, manager: UserModel) -> ManagerResponse:
    groups_result = await session.execute(
        select(ClientGroupModel).where(
            ClientGroupModel.agency_id == manager.agency_id,
            ClientGroupModel.status.notin_(REMOVED_GROUP_STATUSES),
            or_(
                ClientGroupModel.created_by_user_id == manager.id,
                ClientGroupModel.id.in_(
                    select(ManagerGroupAccessModel.group_id).where(ManagerGroupAccessModel.manager_id == manager.id)
                ),
            ),
        )
    )
    groups = list(groups_result.scalars().all())
    access_result = await session.execute(
        select(ManagerGroupAccessModel).where(ManagerGroupAccessModel.manager_id == manager.id)
    )
    access_group_ids = {row.group_id for row in access_result.scalars().all()}
    security_state = (
        await session.execute(
            select(UserSecurityStateModel).where(
                UserSecurityStateModel.user_id == manager.id
            )
        )
    ).scalar_one_or_none()
    return ManagerResponse(
        id=manager.id,
        full_name=manager.full_name,
        email=manager.email,
        role=manager.role,
        agency_id=manager.agency_id,
        is_active=manager.is_active,
        created_at=manager.created_at,
        last_login_at=manager.last_login_at,
        created_groups=[_group_response(group) for group in groups if group.created_by_user_id == manager.id],
        assigned_groups=[_group_response(group) for group in groups if group.id in access_group_ids],
        credential_state=(
            _validated_credential_state(security_state.credential_state)
            if security_state
            else "active"
        ),
    )


async def _delete_by_ids(
    session: AsyncSession,
    model: (
        type[PassportProcessingJobModel]
        | type[PassportSubmissionModel]
        | type[ClientGroupModel]
    ),
    column: InstrumentedAttribute[uuid.UUID],
    ids: list[uuid.UUID],
) -> int:
    if not ids:
        return 0
    result = await session.execute(delete(model).where(column.in_(ids)))
    return int(result.rowcount or 0)


async def _delete_whatsapp_broadcast_data(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID | None,
) -> _WhatsAppPurgeCounts:
    """Delete WhatsApp data in FK-safe order within the caller's transaction."""

    async def delete_model(
        model: (
            type[WhatsAppMessageLogModel]
            | type[WhatsAppRecipientMessageStateModel]
            | type[WhatsAppBroadcastSupportContactModel]
            | type[WhatsAppBroadcastRejectedContactModel]
            | type[WhatsAppBroadcastRecipientModel]
            | type[WhatsAppBroadcastGroupModel]
        ),
    ) -> int:
        stmt = delete(model)
        if agency_id is not None:
            stmt = stmt.where(model.agency_id == agency_id)
        result = await session.execute(stmt)
        return int(result.rowcount or 0)

    # Message logs and delivery states reference both groups and recipients,
    # while support contacts, rejected contacts, and recipients reference groups. Keep this
    # explicit instead of relying on database cascades so counts stay accurate
    # and the order is portable.
    message_logs = await delete_model(WhatsAppMessageLogModel)
    delivery_states = await delete_model(WhatsAppRecipientMessageStateModel)
    support_contacts = await delete_model(WhatsAppBroadcastSupportContactModel)
    rejected_contacts = await delete_model(WhatsAppBroadcastRejectedContactModel)
    recipients = await delete_model(WhatsAppBroadcastRecipientModel)
    broadcast_groups = await delete_model(WhatsAppBroadcastGroupModel)
    return _WhatsAppPurgeCounts(
        broadcast_groups=broadcast_groups,
        recipients=recipients,
        rejected_contacts=rejected_contacts,
        support_contacts=support_contacts,
        message_logs=message_logs,
        delivery_states=delivery_states,
    )


async def _delete_entity_rows(
    session: AsyncSession,
    model: type[NotificationModel],
    *,
    agency_id: uuid.UUID | None,
    group_entity_ids: list[str],
    submission_entity_ids: list[str],
) -> int:
    conditions: list[ColumnElement[bool]] = []
    if group_entity_ids:
        conditions.append(
            (model.entity_type == "client_group") & (model.entity_id.in_(group_entity_ids))
        )
    if submission_entity_ids:
        conditions.append(
            (model.entity_type == "passport_submission") & (model.entity_id.in_(submission_entity_ids))
        )
    if not conditions:
        return 0

    stmt = delete(model).where(or_(*conditions))
    if agency_id is not None:
        stmt = stmt.where(model.agency_id == agency_id)
    result = await session.execute(stmt)
    return int(result.rowcount or 0)
