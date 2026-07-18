"""
Upload Links Routes — /api/v1/upload-links
==========================================
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.dtos.client_group_dtos import (
    CreateClientGroupInputDTO,
    client_group_output_from_entity,
)
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.client_groups.create_client_group_use_case import (
    CreateClientGroupUseCase,
)
from app.application.use_cases.client_groups.create_qualifier_selection_use_case import (
    CreateQualifierSelectionUseCase,
)
from app.application.use_cases.client_groups.delete_client_group_use_case import (
    DeleteClientGroupUseCase,
)
from app.application.use_cases.client_groups.get_client_group_by_token_use_case import (
    GetClientGroupByTokenUseCase,
)
from app.application.use_cases.client_groups.get_qualifier_selection_use_case import (
    GetQualifierSelectionUseCase,
)
from app.application.use_cases.client_groups.list_client_groups_use_case import (
    ListClientGroupsUseCase,
)
from app.application.use_cases.client_groups.restore_client_group_use_case import (
    RestoreClientGroupUseCase,
)
from app.application.use_cases.client_groups.revoke_client_group_use_case import (
    RevokeClientGroupUseCase,
)
from app.core.security.upload_session import is_valid_upload_session_id
from app.domain.entities.entities import User, UserRole
from app.domain.exceptions.exceptions import (
    AuthorizationError,
    EntityNotFoundError,
    PassDetectionError,
)
from app.infrastructure.database.models import (
    ManagerGroupAccessModel,
    NotificationModel,
    PassengerQRTokenModel,
    PassportProcessingJobModel,
    PassportSubmissionModel,
    QualifierSelectionModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.observability.operational_events import (
    is_allowed_operational_reason,
    parse_public_operational_event,
    record_operational_event,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.qualifier_selection_repository import (
    QualifierSelectionRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.infrastructure.storage.passport_object_keys import passport_storage_keys
from app.presentation.api.v1.routes.tour_operations_qr_helpers import qr_expires_at_for_group
from app.presentation.api.v1.schemas.client_group_schemas import (
    ClientGroupResponse,
    CreateClientGroupRequest,
    CreateQualifierSelectionRequest,
    CreateQualifierSelectionResponse,
    PublicFlowTelemetryRequest,
    QualifierSelectionStateResponse,
    UpdateClientGroupRequest,
)
from app.presentation.dependencies.auth import get_current_active_user

router = APIRouter()


# ── Dependency Factories ──────────────────────────────────────────────────

def _get_create_use_case(session: AsyncSession = Depends(get_db_session)) -> CreateClientGroupUseCase:
    return CreateClientGroupUseCase(ClientGroupRepository(session))


def _get_get_by_token_use_case(session: AsyncSession = Depends(get_db_session)) -> GetClientGroupByTokenUseCase:
    return GetClientGroupByTokenUseCase(ClientGroupRepository(session))


def _get_create_qualifier_selection_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> CreateQualifierSelectionUseCase:
    return CreateQualifierSelectionUseCase(
        ClientGroupRepository(session),
        QualifierSelectionRepository(session),
    )


def _get_qualifier_selection_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> GetQualifierSelectionUseCase:
    return GetQualifierSelectionUseCase(
        ClientGroupRepository(session),
        QualifierSelectionRepository(session),
    )


def _get_list_use_case(session: AsyncSession = Depends(get_db_session)) -> ListClientGroupsUseCase:
    return ListClientGroupsUseCase(ClientGroupRepository(session))


def _get_revoke_use_case(session: AsyncSession = Depends(get_db_session)) -> RevokeClientGroupUseCase:
    return RevokeClientGroupUseCase(ClientGroupRepository(session))


def _get_delete_use_case(session: AsyncSession = Depends(get_db_session)) -> DeleteClientGroupUseCase:
    return DeleteClientGroupUseCase(ClientGroupRepository(session))


def _get_restore_use_case(session: AsyncSession = Depends(get_db_session)) -> RestoreClientGroupUseCase:
    return RestoreClientGroupUseCase(ClientGroupRepository(session))


def _owner_scope_for(user: User) -> uuid.UUID | None:
    return user.id if user.role == UserRole.AGENCY_STAFF else None


# ── Routes ────────────────────────────────────────────────────────────────

@router.post(
    "",
    response_model=ClientGroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a secure, time-limited upload link",
)
async def create_client_group(
    request: CreateClientGroupRequest,
    current_user: User = Depends(get_current_active_user),
    use_case: CreateClientGroupUseCase = Depends(_get_create_use_case),
) -> ClientGroupResponse:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must be associated with an agency to create upload links."
        )

    dto = CreateClientGroupInputDTO(
        name=request.name,
        destination=request.destination,
        travel_date=request.travel_date,
        return_date=request.return_date,
        package_name=request.package_name,
        departure_cities=request.departure_cities,
        base_city_enabled=request.base_city_enabled,
        nearest_international_airport_enabled=request.nearest_international_airport_enabled,
        staff_code_enabled=request.staff_code_enabled,
        meal_preference_enabled=request.meal_preference_enabled,
        require_selfie=request.require_selfie,
        allow_files_from_device=request.allow_files_from_device,
        ask_nearest_domestic_airport=request.ask_nearest_domestic_airport,
        relation_with_qualifier_enabled=request.relation_with_qualifier_enabled,
        notes=request.notes,
    )

    result = await use_case.execute(
        dto=dto,
        agency_id=current_user.agency_id,
        created_by_user_id=current_user.id,
    )
    return ClientGroupResponse.model_validate(result)


@router.get(
    "",
    response_model=list[ClientGroupResponse],
    status_code=status.HTTP_200_OK,
    summary="List upload links for the current user's agency",
)
async def list_client_groups(
    skip: int = 0,
    limit: int = 50,
    status_filter: str | None = None,
    current_user: User = Depends(get_current_active_user),
    use_case: ListClientGroupsUseCase = Depends(_get_list_use_case),
) -> list[ClientGroupResponse]:
    if not current_user.agency_id:
        return []
    if status_filter == "deleted" and current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only super admins can view deleted group data")

    results = await use_case.execute(
        agency_id=current_user.agency_id,
        skip=skip,
        limit=limit,
        status_filter=status_filter,
        created_by_user_id=None if status_filter == "deleted" else _owner_scope_for(current_user),
        visible_to_user=None if status_filter == "deleted" else current_user,
    )
    return [ClientGroupResponse.model_validate(r) for r in results]


@router.get(
    "/token/{token}",
    response_model=ClientGroupResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve and validate upload link details by token (Public)",
)
async def get_client_group_by_token(
    token: str,
    use_case: GetClientGroupByTokenUseCase = Depends(_get_get_by_token_use_case),
) -> ClientGroupResponse:
    try:
        result = await use_case.execute(token=token)
        return ClientGroupResponse.model_validate(result)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except PassDetectionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


@router.post(
    "/token/{token}/telemetry",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Record a bounded public upload quality signal",
)
async def record_public_flow_telemetry(
    token: str,
    body: PublicFlowTelemetryRequest,
    upload_session_id: str = Header(
        ...,
        alias="X-Upload-Session-ID",
        min_length=8,
        max_length=128,
    ),
    use_case: GetClientGroupByTokenUseCase = Depends(
        _get_get_by_token_use_case
    ),
) -> Response:
    """Accept only fixed, PII-free events for an active upload link."""

    if not is_valid_upload_session_id(upload_session_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload session identifier is invalid.",
        )
    event = parse_public_operational_event(body.event)
    if event is None or not is_allowed_operational_reason(
        event,
        body.reason,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported upload telemetry event.",
        )

    try:
        await use_case.execute(token=token)
    except (EntityNotFoundError, PassDetectionError):
        # Match the upload reconciliation privacy contract: invalid, closed,
        # and expired bearer links do not become a telemetry oracle.
        return Response(
            status_code=status.HTTP_204_NO_CONTENT,
            headers={"Cache-Control": "private, no-store"},
        )

    record_operational_event(event, body.reason)
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post(
    "/token/{token}/qualifier-selection",
    response_model=CreateQualifierSelectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Persist a Relation with Qualifier choice before upload (Public)",
)
async def create_qualifier_selection(
    token: str,
    request: CreateQualifierSelectionRequest,
    use_case: CreateQualifierSelectionUseCase = Depends(
        _get_create_qualifier_selection_use_case
    ),
) -> CreateQualifierSelectionResponse:
    try:
        result = await use_case.execute(
            group_token=token,
            is_self=request.is_self,
            relation_code=request.relation_code,
        )
        return CreateQualifierSelectionResponse.model_validate(result)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        )
    except PassDetectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.message,
        )


@router.get(
    "/token/{token}/qualifier-selection",
    response_model=QualifierSelectionStateResponse,
    status_code=status.HTTP_200_OK,
    summary="Resume a persisted Relation with Qualifier choice (Public)",
)
async def get_qualifier_selection(
    token: str,
    qualifier_selection_token: str = Header(
        ...,
        alias="X-Qualifier-Selection-Token",
        min_length=32,
        max_length=256,
    ),
    use_case: GetQualifierSelectionUseCase = Depends(
        _get_qualifier_selection_use_case
    ),
) -> QualifierSelectionStateResponse:
    try:
        result = await use_case.execute(
            group_token=token,
            selection_token=qualifier_selection_token,
        )
        return QualifierSelectionStateResponse.model_validate(result)
    except EntityNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.message,
        )
    except PassDetectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=exc.message,
        )


@router.post(
    "/{link_id}/revoke",
    response_model=ClientGroupResponse,
    status_code=status.HTTP_200_OK,
    summary="Revoke an upload link",
)
async def revoke_client_group(
    link_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    use_case: RevokeClientGroupUseCase = Depends(_get_revoke_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> ClientGroupResponse:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions"
        )

    group = await ClientGroupRepository(session).get_by_id(link_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found")
    try:
        await AuthorizationPolicy(session).require_manage_group(current_user, group)
        result = await use_case.execute(
            link_id=link_id,
            agency_id=current_user.agency_id,
            created_by_user_id=None,
        )
        return ClientGroupResponse.model_validate(result)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)
    except PassDetectionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


@router.patch(
    "/{link_id}",
    response_model=ClientGroupResponse,
    status_code=status.HTTP_200_OK,
    summary="Rename a client group",
)
async def update_client_group(
    link_id: uuid.UUID,
    request: UpdateClientGroupRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ClientGroupResponse:
    if not current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    repo = ClientGroupRepository(session)
    group = await repo.get_by_id(link_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found")
    try:
        await AuthorizationPolicy(session).require_manage_group(current_user, group)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)

    previous_qualifier_enabled = group.relation_with_qualifier_enabled
    group.update_configuration(
        name=request.name,
        destination=request.destination,
        travel_date=request.travel_date,
        return_date=request.return_date,
        package_name=request.package_name,
        departure_cities=request.departure_cities,
        base_city_enabled=request.base_city_enabled,
        nearest_international_airport_enabled=request.nearest_international_airport_enabled,
        staff_code_enabled=request.staff_code_enabled,
        meal_preference_enabled=request.meal_preference_enabled,
        require_selfie=request.require_selfie,
        allow_files_from_device=request.allow_files_from_device,
        ask_nearest_domestic_airport=request.ask_nearest_domestic_airport,
        relation_with_qualifier_enabled=request.relation_with_qualifier_enabled,
        notes=request.notes,
    )
    await repo.update(group)
    passenger_ids_result = await session.execute(
        select(PassportSubmissionModel.id).where(PassportSubmissionModel.group_id == group.id)
    )
    passenger_ids = list(passenger_ids_result.scalars().all())
    if passenger_ids:
        await session.execute(
            update(PassengerQRTokenModel)
            .where(
                PassengerQRTokenModel.passenger_id.in_(passenger_ids),
                PassengerQRTokenModel.revoked_at.is_(None),
            )
            .values(expires_at=qr_expires_at_for_group(group))
        )
    await AuditLogRepository(session).record(
        action="client_group_renamed",
        entity_type="client_group",
        entity_id=str(group.id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={"name": group.name},
    )
    if previous_qualifier_enabled != group.relation_with_qualifier_enabled:
        await AuditLogRepository(session).record(
            action="client_group_qualifier_configuration_updated",
            entity_type="client_group",
            entity_id=str(group.id),
            agency_id=group.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "previous_enabled": previous_qualifier_enabled,
                "enabled": group.relation_with_qualifier_enabled,
            },
        )
    return ClientGroupResponse.model_validate(
        client_group_output_from_entity(group)
    )


@router.delete(
    "/{link_id}",
    response_model=ClientGroupResponse,
    status_code=status.HTTP_200_OK,
    summary="Archive a client group",
)
async def delete_client_group(
    link_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    use_case: DeleteClientGroupUseCase = Depends(_get_delete_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> ClientGroupResponse:
    if not current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    group = await ClientGroupRepository(session).get_by_id(link_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found")
    try:
        await AuthorizationPolicy(session).require_delete_data(current_user, group)
        result = await use_case.execute(
            group_id=link_id,
            agency_id=current_user.agency_id,
            created_by_user_id=None,
        )
        return ClientGroupResponse.model_validate(result)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)
    except PassDetectionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


@router.delete(
    "/{link_id}/permanent",
    status_code=status.HTTP_200_OK,
    summary="Permanently delete an archived client group",
)
async def permanently_delete_client_group(
    link_id: uuid.UUID,
    retain_records: bool = True,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, int | bool]:
    if not current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    repo = ClientGroupRepository(session)
    group = await repo.get_by_id(link_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found")
    try:
        await AuthorizationPolicy(session).require_delete_data(current_user, group, permanent=True)
    except AuthorizationError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=exc.message)
    if group.status.value != "archived":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Archive the group before permanent deletion")

    submission_rows = await session.execute(
        select(
            PassportSubmissionModel.id,
            PassportSubmissionModel.image_s3_key,
            PassportSubmissionModel.thumbnail_s3_key,
            PassportSubmissionModel.passport_back_s3_key,
            PassportSubmissionModel.passport_photo_s3_key,
        ).where(PassportSubmissionModel.group_id == link_id)
    )
    submissions = list(submission_rows.all())
    submission_ids = [row.id for row in submissions]
    storage_keys = passport_storage_keys(submissions)

    await session.execute(delete(ManagerGroupAccessModel).where(ManagerGroupAccessModel.group_id == link_id))
    deleted_storage_objects = 0
    deleted_processing_jobs = 0
    deleted_passport_submissions = 0
    deleted_qualifier_selections = 0
    if not retain_records:
        deleted_storage_objects = await MinioStorageRepository().delete_files(storage_keys)
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
        qualifier_result = await session.execute(
            delete(QualifierSelectionModel).where(
                QualifierSelectionModel.group_id == link_id
            )
        )
        deleted_qualifier_selections = int(
            getattr(qualifier_result, "rowcount", 0) or 0
        )
    await session.execute(
        delete(NotificationModel).where(
            NotificationModel.entity_type == "client_group",
            NotificationModel.entity_id == str(link_id),
        )
    )
    group.mark_deleted(passport_count=len(submissions), retain_records=retain_records)
    await repo.update(group)
    await AuditLogRepository(session).record(
        action="client_group_deleted_with_retention" if retain_records else "client_group_deleted_with_data_removal",
        entity_type="client_group",
        entity_id=str(link_id),
        agency_id=current_user.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "group_name": group.name,
            "retained_records": retain_records,
            "historical_passport_count": len(submissions),
            "deleted_passport_submissions": deleted_passport_submissions,
            "deleted_processing_jobs": deleted_processing_jobs,
            "deleted_qualifier_selections": deleted_qualifier_selections,
            "deleted_storage_objects": deleted_storage_objects,
        },
    )
    return {
        "deleted": True,
        "retained_records": retain_records,
        "historical_passport_count": len(submissions),
        "deleted_passport_submissions": deleted_passport_submissions,
        "deleted_processing_jobs": deleted_processing_jobs,
        "deleted_qualifier_selections": deleted_qualifier_selections,
        "deleted_storage_objects": deleted_storage_objects,
    }


@router.post(
    "/{link_id}/restore",
    response_model=ClientGroupResponse,
    status_code=status.HTTP_200_OK,
    summary="Restore an archived or retained deleted client group",
)
async def restore_client_group(
    link_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    use_case: RestoreClientGroupUseCase = Depends(_get_restore_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> ClientGroupResponse:
    if not current_user.agency_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    group = await ClientGroupRepository(session).get_by_id(link_id)
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found")
    try:
        await AuthorizationPolicy(session).require_manage_group(current_user, group)
        result = await use_case.execute(
            group_id=link_id,
            agency_id=current_user.agency_id,
            created_by_user_id=None,
            allow_deleted_restore=current_user.role == UserRole.SUPER_ADMIN,
        )
        return ClientGroupResponse.model_validate(result)
    except EntityNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=e.message)
    except AuthorizationError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=e.message)
    except PassDetectionError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=e.message)


async def _delete_by_ids(session: AsyncSession, model, column, ids: list) -> int:  # type: ignore[no-untyped-def]
    if not ids:
        return 0
    result = await session.execute(delete(model).where(column.in_(ids)))
    return int(result.rowcount or 0)
