"""
Admin Routes
============
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.password import hash_password
from app.domain.entities.entities import PassportProcessingStatus, User, UserRole
from app.infrastructure.database.models import (
    AgencyModel,
    AuditLogModel,
    ClientGroupModel,
    ManagerGroupAccessModel,
    NotificationModel,
    PassportProcessingJobModel,
    PassportSubmissionModel,
    PlatformSettingModel,
    UserModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.presentation.api.v1.schemas.operations_schemas import (
    AdminOverviewResponse,
    AssignManagerGroupsRequest,
    CreateManagerRequest,
    DeleteManagerRequest,
    DeleteManagerResponse,
    ManagerGroupAccessResponse,
    ManagerResponse,
    PlatformSettingsResponse,
    PurgePassportDataResponse,
    UpdatePlatformSettingsRequest,
)
from app.presentation.dependencies.auth import require_role

router = APIRouter()
PLATFORM_SETTINGS_KEY = "global"
DEFAULT_PLATFORM_SETTINGS = PlatformSettingsResponse().model_dump(exclude={"updated_at"})


def _manager_scope(current_user: User) -> list:
    if current_user.role == UserRole.SUPER_ADMIN:
        return [UserModel.role == UserRole.AGENCY_STAFF.value]
    return [
        UserModel.role == UserRole.AGENCY_STAFF.value,
        UserModel.agency_id == current_user.agency_id,
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
            PassportSubmissionModel.status.in_((
                PassportProcessingStatus.CLIENT_SUBMITTED.value,
                PassportProcessingStatus.CONFIRMED.value,
            )),
        ),
    )
    pending = await _count(
        session,
        select(func.count()).select_from(PassportSubmissionModel).join(
            ClientGroupModel,
            PassportSubmissionModel.group_id == ClientGroupModel.id,
        ).where(
            *passport_scope_filter,
            PassportSubmissionModel.status == PassportProcessingStatus.REVIEW_REQUIRED.value,
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
            PassportSubmissionModel.status == PassportProcessingStatus.CLIENT_SUBMITTED.value,
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
        )
        for user in managers
    ]


@router.post(
    "/managers",
    response_model=ManagerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a limited manager account",
)
async def create_manager(
    body: CreateManagerRequest,
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
        hashed_password=hash_password(body.password),
        full_name=body.full_name.strip(),
        role=UserRole.AGENCY_STAFF.value,
        agency_id=current_user.agency_id,
        is_active=True,
    )
    session.add(manager)
    await session.flush()

    return ManagerResponse(
        id=manager.id,
        full_name=manager.full_name,
        email=manager.email,
        role=manager.role,
        agency_id=manager.agency_id,
        is_active=manager.is_active,
        created_at=manager.created_at,
        last_login_at=manager.last_login_at,
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
)
async def update_platform_settings(
    body: UpdatePlatformSettingsRequest,
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> PlatformSettingsResponse:
    result = await session.execute(
        select(PlatformSettingModel).where(PlatformSettingModel.key == PLATFORM_SETTINGS_KEY)
    )
    row = result.scalar_one_or_none()
    value = body.model_dump()
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
        metadata=value,
    )
    return PlatformSettingsResponse(**row.value, updated_at=row.updated_at)


@router.get(
    "/groups",
    response_model=list[ManagerGroupAccessResponse],
    status_code=status.HTTP_200_OK,
    summary="List groups available for manager access assignment",
)
async def list_admin_groups(
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> list[ManagerGroupAccessResponse]:
    filters = [] if current_user.role == UserRole.SUPER_ADMIN else [ClientGroupModel.agency_id == current_user.agency_id]
    result = await session.execute(
        select(ClientGroupModel)
        .where(*filters)
        .order_by(ClientGroupModel.created_at.desc())
    )
    return [_group_response(group) for group in result.scalars().all()]


@router.put(
    "/managers/{manager_id}/groups",
    response_model=ManagerResponse,
    status_code=status.HTTP_200_OK,
    summary="Replace a manager's extra assigned group access",
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
)
async def delete_manager(
    manager_id: uuid.UUID,
    body: DeleteManagerRequest | None = None,
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> DeleteManagerResponse:
    manager_result = await session.execute(select(UserModel).where(UserModel.id == manager_id, *_manager_scope(current_user)))
    manager = manager_result.scalar_one_or_none()
    if not manager:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manager was not found")

    delete_owned_data = bool(body and body.delete_owned_data)
    response = DeleteManagerResponse(
        deleted_manager_id=manager.id,
        deleted_owned_data=delete_owned_data,
    )

    if delete_owned_data:
        group_rows = await session.execute(select(ClientGroupModel.id).where(ClientGroupModel.created_by_user_id == manager.id))
        group_ids = list(group_rows.scalars().all())

        submission_rows = await session.execute(
            select(
                PassportSubmissionModel.id,
                PassportSubmissionModel.image_s3_key,
                PassportSubmissionModel.thumbnail_s3_key,
            ).where(PassportSubmissionModel.group_id.in_(group_ids))
        ) if group_ids else None
        submissions = list(submission_rows.all()) if submission_rows else []
        submission_ids = [row.id for row in submissions]
        storage_keys = [row.image_s3_key for row in submissions if row.image_s3_key]
        storage_keys.extend(row.thumbnail_s3_key for row in submissions if row.thumbnail_s3_key)

        response.deleted_storage_objects = await MinioStorageRepository().delete_files(storage_keys)
        group_entity_ids = [str(group_id) for group_id in group_ids]
        submission_entity_ids = [str(submission_id) for submission_id in submission_ids]
        response.deleted_notifications = await _delete_entity_rows(
            session,
            NotificationModel,
            agency_id=manager.agency_id,
            group_entity_ids=group_entity_ids,
            submission_entity_ids=submission_entity_ids,
        )
        response.deleted_audit_logs = await _delete_entity_rows(
            session,
            AuditLogModel,
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
            "manager_email": manager.email,
            "manager_name": manager.full_name,
            "delete_owned_data": delete_owned_data,
            **response.model_dump(mode="json"),
        },
    )
    await session.delete(manager)
    await session.flush()
    return response


@router.delete(
    "/passport-data",
    response_model=PurgePassportDataResponse,
    status_code=status.HTTP_200_OK,
    summary="Permanently delete passport submissions and client groups",
)
async def purge_passport_data(
    current_user: User = Depends(require_role([UserRole.SUPER_ADMIN, UserRole.AGENCY_ADMIN])),
    session: AsyncSession = Depends(get_db_session),
) -> PurgePassportDataResponse:
    if current_user.role != UserRole.SUPER_ADMIN and not current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This admin account is not assigned to an agency")

    group_filter = [] if current_user.role == UserRole.SUPER_ADMIN else [ClientGroupModel.agency_id == current_user.agency_id]
    passport_filter = [] if current_user.role == UserRole.SUPER_ADMIN else [PassportSubmissionModel.agency_id == current_user.agency_id]

    group_rows = await session.execute(select(ClientGroupModel.id).where(*group_filter))
    group_ids = list(group_rows.scalars().all())

    submission_rows = await session.execute(
        select(
            PassportSubmissionModel.id,
            PassportSubmissionModel.image_s3_key,
            PassportSubmissionModel.thumbnail_s3_key,
        ).where(*passport_filter)
    )
    submissions = list(submission_rows.all())
    submission_ids = [row.id for row in submissions]
    storage_keys = [row.image_s3_key for row in submissions if row.image_s3_key]
    storage_keys.extend(row.thumbnail_s3_key for row in submissions if row.thumbnail_s3_key)

    deleted_storage_objects = await MinioStorageRepository().delete_files(storage_keys)

    group_entity_ids = [str(group_id) for group_id in group_ids]
    submission_entity_ids = [str(submission_id) for submission_id in submission_ids]

    deleted_notifications = await _delete_entity_rows(
        session,
        NotificationModel,
        agency_id=None if current_user.role == UserRole.SUPER_ADMIN else current_user.agency_id,
        group_entity_ids=group_entity_ids,
        submission_entity_ids=submission_entity_ids,
    )
    deleted_audit_logs = await _delete_entity_rows(
        session,
        AuditLogModel,
        agency_id=None if current_user.role == UserRole.SUPER_ADMIN else current_user.agency_id,
        group_entity_ids=group_entity_ids,
        submission_entity_ids=submission_entity_ids,
    )

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

    response = PurgePassportDataResponse(
        deleted_client_groups=deleted_client_groups,
        deleted_passport_submissions=deleted_passport_submissions,
        deleted_processing_jobs=deleted_processing_jobs,
        deleted_notifications=deleted_notifications,
        deleted_audit_logs=deleted_audit_logs,
        deleted_storage_objects=deleted_storage_objects,
    )

    await AuditLogRepository(session).record(
        action="passport_data_purged",
        entity_type="platform" if current_user.role == UserRole.SUPER_ADMIN else "agency",
        agency_id=None if current_user.role == UserRole.SUPER_ADMIN else current_user.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        entity_id=None if current_user.role == UserRole.SUPER_ADMIN else str(current_user.agency_id),
        metadata=response.model_dump(),
    )
    return response


async def _count(session: AsyncSession, stmt) -> int:  # type: ignore[no-untyped-def]
    result = await session.execute(stmt)
    return int(result.scalar_one())


async def _load_platform_settings(session: AsyncSession) -> PlatformSettingsResponse:
    result = await session.execute(select(PlatformSettingModel).where(PlatformSettingModel.key == PLATFORM_SETTINGS_KEY))
    row = result.scalar_one_or_none()
    if not row:
        return PlatformSettingsResponse(**DEFAULT_PLATFORM_SETTINGS)
    return PlatformSettingsResponse(**{**DEFAULT_PLATFORM_SETTINGS, **row.value}, updated_at=row.updated_at)


def _group_response(group: ClientGroupModel) -> ManagerGroupAccessResponse:
    return ManagerGroupAccessResponse(
        id=group.id,
        name=group.name,
        status=group.status,
        created_by_user_id=group.created_by_user_id,
    )


async def _manager_response(session: AsyncSession, manager: UserModel) -> ManagerResponse:
    groups_result = await session.execute(
        select(ClientGroupModel).where(
            ClientGroupModel.agency_id == manager.agency_id,
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
    )


async def _delete_by_ids(session: AsyncSession, model, column, ids: list) -> int:  # type: ignore[no-untyped-def]
    if not ids:
        return 0
    result = await session.execute(delete(model).where(column.in_(ids)))
    return int(result.rowcount or 0)


async def _delete_entity_rows(
    session: AsyncSession,
    model,
    *,
    agency_id,
    group_entity_ids: list[str],
    submission_entity_ids: list[str],
) -> int:  # type: ignore[no-untyped-def]
    conditions = []
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
