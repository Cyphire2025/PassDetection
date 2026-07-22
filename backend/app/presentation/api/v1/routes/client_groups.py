"""
Upload Links Routes — /api/v1/upload-links
==========================================
"""

from __future__ import annotations

import uuid
from math import ceil
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Response,
    status,
)
from sqlalchemy import and_, delete, func, select, update
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
from app.application.use_cases.whatsapp.contact_normalization import (
    normalize_whatsapp_phone,
)
from app.application.use_cases.whatsapp.group_submission_matching import (
    RecipientForComparison,
    SubmissionForComparison,
    compare_group_submissions,
    filter_and_sort_match_rows,
    summarize_match_rows,
)
from app.core.security.upload_session import is_valid_upload_session_id
from app.domain.entities.entities import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
    User,
    UserRole,
)
from app.domain.exceptions.exceptions import (
    AuthorizationError,
    EntityNotFoundError,
    PassDetectionError,
)
from app.infrastructure.database.models import (
    ClientGroupWhatsAppBroadcastLinkModel,
    ManagerGroupAccessModel,
    NotificationModel,
    PassengerQRTokenModel,
    PassportProcessingJobModel,
    PassportSubmissionModel,
    QualifierSelectionModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.observability.operational_events import (
    is_allowed_operational_reason,
    parse_public_operational_event,
    record_operational_event,
)
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_image_crop_repository import (
    PassportImageCropRepository,
)
from app.infrastructure.repositories.qualifier_selection_repository import (
    QualifierSelectionRepository,
)
from app.infrastructure.storage.minio_repository import MinioStorageRepository
from app.infrastructure.storage.passport_object_keys import passport_storage_keys
from app.presentation.api.v1.routes.tour_operations_qr_helpers import qr_expires_at_for_group
from app.presentation.api.v1.schemas.client_group_schemas import (
    ClientGroupResponse,
    ClientGroupWhatsAppLinksResponse,
    ClientGroupWhatsAppMatchesResponse,
    CreateClientGroupRequest,
    CreateQualifierSelectionRequest,
    CreateQualifierSelectionResponse,
    PublicFlowTelemetryRequest,
    QualifierSelectionStateResponse,
    ReplaceWhatsAppBroadcastLinksRequest,
    UpdateClientGroupRequest,
    WhatsAppBroadcastSummaryResponse,
    WhatsAppRecipientImportedFieldsResponse,
    WhatsAppSubmissionMatchCountsResponse,
    WhatsAppSubmissionMatchEvidenceResponse,
    WhatsAppSubmissionMatchRowResponse,
)
from app.presentation.dependencies.auth import (
    WHATSAPP_BROADCAST_ROLES,
    get_current_active_user,
)

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


def _require_whatsapp_broadcast_access(user: User) -> None:
    if user.role not in WHATSAPP_BROADCAST_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="WhatsApp broadcast access is not available for this account.",
        )


async def _broadcast_summaries(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    broadcast_ids: list[uuid.UUID] | None = None,
) -> list[WhatsAppBroadcastSummaryResponse]:
    stmt = (
        select(
            WhatsAppBroadcastGroupModel,
            func.count(WhatsAppBroadcastRecipientModel.id).label(
                "recipient_count"
            ),
        )
        .outerjoin(
            WhatsAppBroadcastRecipientModel,
            and_(
                WhatsAppBroadcastRecipientModel.broadcast_group_id
                == WhatsAppBroadcastGroupModel.id,
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            ),
        )
        .where(WhatsAppBroadcastGroupModel.agency_id == agency_id)
    )
    if broadcast_ids is not None:
        if not broadcast_ids:
            return []
        stmt = stmt.where(
            WhatsAppBroadcastGroupModel.id.in_(broadcast_ids)
        )
    result = await session.execute(
        stmt.group_by(WhatsAppBroadcastGroupModel.id).order_by(
            func.lower(WhatsAppBroadcastGroupModel.name).asc(),
            WhatsAppBroadcastGroupModel.id.asc(),
        )
    )
    return [
        WhatsAppBroadcastSummaryResponse(
            id=broadcast.id,
            name=broadcast.name,
            recipient_count=int(recipient_count or 0),
            created_at=broadcast.created_at,
            updated_at=broadcast.updated_at,
        )
        for broadcast, recipient_count in result.all()
    ]


async def _validate_broadcast_ids(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    broadcast_ids: list[uuid.UUID],
) -> list[WhatsAppBroadcastSummaryResponse]:
    summaries = await _broadcast_summaries(
        session,
        agency_id=agency_id,
        broadcast_ids=broadcast_ids,
    )
    if {summary.id for summary in summaries} != set(broadcast_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "One or more WhatsApp broadcast groups are unavailable "
                "for this agency."
            ),
        )
    return summaries


async def _linked_broadcast_summaries_by_group(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    client_group_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[WhatsAppBroadcastSummaryResponse]]:
    if not client_group_ids:
        return {}
    result = await session.execute(
        select(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id,
            WhatsAppBroadcastGroupModel,
            func.count(WhatsAppBroadcastRecipientModel.id).label(
                "recipient_count"
            ),
        )
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id
            == ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
        )
        .outerjoin(
            WhatsAppBroadcastRecipientModel,
            and_(
                WhatsAppBroadcastRecipientModel.broadcast_group_id
                == WhatsAppBroadcastGroupModel.id,
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            ),
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id.in_(
                client_group_ids
            ),
        )
        .group_by(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id,
            WhatsAppBroadcastGroupModel.id,
        )
        .order_by(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id.asc(),
            func.lower(WhatsAppBroadcastGroupModel.name).asc(),
            WhatsAppBroadcastGroupModel.id.asc(),
        )
    )
    summaries: dict[
        uuid.UUID, list[WhatsAppBroadcastSummaryResponse]
    ] = {group_id: [] for group_id in client_group_ids}
    for group_id, broadcast, recipient_count in result.all():
        summaries.setdefault(group_id, []).append(
            WhatsAppBroadcastSummaryResponse(
                id=broadcast.id,
                name=broadcast.name,
                recipient_count=int(recipient_count or 0),
                created_at=broadcast.created_at,
                updated_at=broadcast.updated_at,
            )
        )
    return summaries


async def _replace_whatsapp_links(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    broadcast_ids: list[uuid.UUID],
) -> tuple[list[WhatsAppBroadcastSummaryResponse], list[uuid.UUID], bool]:
    summaries = await _validate_broadcast_ids(
        session,
        agency_id=agency_id,
        broadcast_ids=broadcast_ids,
    )
    existing_result = await session.execute(
        select(
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id
        ).where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id
            == group_id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
        )
    )
    previous_ids = sorted(set(existing_result.scalars().all()), key=str)
    requested_ids = sorted(set(broadcast_ids), key=str)
    changed = previous_ids != requested_ids
    if changed:
        await session.execute(
            delete(ClientGroupWhatsAppBroadcastLinkModel).where(
                ClientGroupWhatsAppBroadcastLinkModel.client_group_id
                == group_id,
                ClientGroupWhatsAppBroadcastLinkModel.agency_id
                == agency_id,
            )
        )
        session.add_all(
            [
                ClientGroupWhatsAppBroadcastLinkModel(
                    id=uuid.uuid4(),
                    client_group_id=group_id,
                    broadcast_group_id=broadcast_id,
                    agency_id=agency_id,
                    created_by_user_id=created_by_user_id,
                )
                for broadcast_id in requested_ids
            ]
        )
        await session.flush()
    return summaries, previous_ids, changed


async def _require_managed_group(
    session: AsyncSession,
    current_user: User,
    link_id: uuid.UUID,
):  # type: ignore[no-untyped-def]
    group = await ClientGroupRepository(session).get_by_id(link_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client group was not found",
        )
    try:
        await AuthorizationPolicy(session).require_manage_group(
            current_user, group
        )
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc
    return group


async def _require_viewable_group(
    session: AsyncSession,
    current_user: User,
    link_id: uuid.UUID,
):  # type: ignore[no-untyped-def]
    group = await ClientGroupRepository(session).get_by_id(link_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client group was not found",
        )
    try:
        await AuthorizationPolicy(session).require_view_group(
            current_user, group
        )
    except AuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc
    return group


async def _unique_linked_recipient_count(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
) -> int:
    result = await session.execute(
        select(
            WhatsAppBroadcastRecipientModel.normalized_phone_number
        )
        .join(
            ClientGroupWhatsAppBroadcastLinkModel,
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id
            == WhatsAppBroadcastRecipientModel.broadcast_group_id,
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id
            == group_id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
            WhatsAppBroadcastRecipientModel.agency_id == agency_id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
        )
    )
    return len(
        {
            normalized
            for value in result.scalars().all()
            if (normalized := normalize_whatsapp_phone(value))
        }
    )


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
    session: AsyncSession = Depends(get_db_session),
) -> ClientGroupResponse:
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must be associated with an agency to create upload links."
        )

    if request.whatsapp_broadcast_group_ids:
        _require_whatsapp_broadcast_access(current_user)

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
        agent_employee_code_enabled=request.agent_employee_code_enabled,
        meal_preference_enabled=request.meal_preference_enabled,
        require_selfie=request.require_selfie,
        allow_files_from_device=request.allow_files_from_device,
        ask_nearest_domestic_airport=request.ask_nearest_domestic_airport,
        relation_with_qualifier_enabled=request.relation_with_qualifier_enabled,
        notes=request.notes,
    )

    await _validate_broadcast_ids(
        session,
        agency_id=current_user.agency_id,
        broadcast_ids=request.whatsapp_broadcast_group_ids,
    )
    result = await use_case.execute(
        dto=dto,
        agency_id=current_user.agency_id,
        created_by_user_id=current_user.id,
    )
    linked, _, _ = await _replace_whatsapp_links(
        session,
        group_id=result.id,
        agency_id=current_user.agency_id,
        created_by_user_id=current_user.id,
        broadcast_ids=request.whatsapp_broadcast_group_ids,
    )
    await AuditLogRepository(session).record(
        action="client_group_created",
        entity_type="client_group",
        entity_id=str(result.id),
        agency_id=current_user.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "whatsapp_broadcast_count": len(linked),
            "whatsapp_broadcast_group_ids": [
                str(summary.id) for summary in linked
            ],
        },
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
    "/whatsapp-broadcast-options",
    response_model=list[WhatsAppBroadcastSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List same-agency WhatsApp broadcasts available to new groups",
)
async def list_whatsapp_broadcast_options_for_create(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[WhatsAppBroadcastSummaryResponse]:
    _require_whatsapp_broadcast_access(current_user)
    if not current_user.agency_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must be associated with an agency.",
        )
    return await _broadcast_summaries(
        session,
        agency_id=current_user.agency_id,
    )


@router.get(
    "/{link_id}/whatsapp-broadcast-options",
    response_model=list[WhatsAppBroadcastSummaryResponse],
    status_code=status.HTTP_200_OK,
    summary="List WhatsApp broadcasts available to an existing group",
)
async def list_whatsapp_broadcast_options_for_group(
    link_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[WhatsAppBroadcastSummaryResponse]:
    _require_whatsapp_broadcast_access(current_user)
    group = await _require_managed_group(
        session, current_user, link_id
    )
    return await _broadcast_summaries(
        session,
        agency_id=group.agency_id,
    )


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


@router.get(
    "/{link_id}/whatsapp-links",
    response_model=ClientGroupWhatsAppLinksResponse,
    status_code=status.HTTP_200_OK,
    summary="Get WhatsApp broadcasts linked to an upload group",
)
async def get_client_group_whatsapp_links(
    link_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ClientGroupWhatsAppLinksResponse:
    _require_whatsapp_broadcast_access(current_user)
    group = await _require_viewable_group(
        session, current_user, link_id
    )
    can_manage = await AuthorizationPolicy(session).can_manage_group(
        current_user, group
    )
    linked = await _linked_broadcast_summaries_by_group(
        session,
        agency_id=group.agency_id,
        client_group_ids=[group.id],
    )
    summaries = linked.get(group.id, [])
    return ClientGroupWhatsAppLinksResponse(
        client_group_id=group.id,
        broadcasts=summaries,
        broadcast_count=len(summaries),
        recipient_count=await _unique_linked_recipient_count(
            session,
            group_id=group.id,
            agency_id=group.agency_id,
        ),
        can_manage=can_manage,
    )


@router.put(
    "/{link_id}/whatsapp-links",
    response_model=ClientGroupWhatsAppLinksResponse,
    status_code=status.HTTP_200_OK,
    summary="Replace WhatsApp broadcasts linked to an upload group",
)
async def replace_client_group_whatsapp_links(
    link_id: uuid.UUID,
    body: ReplaceWhatsAppBroadcastLinksRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ClientGroupWhatsAppLinksResponse:
    _require_whatsapp_broadcast_access(current_user)
    group = await _require_managed_group(
        session, current_user, link_id
    )
    summaries, previous_ids, changed = await _replace_whatsapp_links(
        session,
        group_id=group.id,
        agency_id=group.agency_id,
        created_by_user_id=current_user.id,
        broadcast_ids=body.whatsapp_broadcast_group_ids,
    )
    await AuditLogRepository(session).record(
        action="client_group_whatsapp_links_replaced",
        entity_type="client_group",
        entity_id=str(group.id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "changed": changed,
            "previous_broadcast_count": len(previous_ids),
            "broadcast_count": len(summaries),
            "whatsapp_broadcast_group_ids": [
                str(summary.id) for summary in summaries
            ],
        },
    )
    return ClientGroupWhatsAppLinksResponse(
        client_group_id=group.id,
        broadcasts=summaries,
        broadcast_count=len(summaries),
        recipient_count=await _unique_linked_recipient_count(
            session,
            group_id=group.id,
            agency_id=group.agency_id,
        ),
        can_manage=True,
    )


@router.get(
    "/{link_id}/whatsapp-matches",
    response_model=ClientGroupWhatsAppMatchesResponse,
    status_code=status.HTTP_200_OK,
    summary="Compare linked WhatsApp recipients with passport submissions",
)
async def get_client_group_whatsapp_matches(
    link_id: uuid.UUID,
    broadcast_id: uuid.UUID | None = None,
    match_status: Literal[
        "all",
        "submitted",
        "not_submitted",
        "multiple_submissions",
        "needs_review",
        "unmatched_submission",
    ] = Query(default="all", alias="status"),
    sort_by: Literal[
        "name", "phone", "status", "broadcast", "updated_at"
    ] = "name",
    sort_order: Literal["asc", "desc"] = "asc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ClientGroupWhatsAppMatchesResponse:
    _require_whatsapp_broadcast_access(current_user)
    group = await _require_viewable_group(
        session, current_user, link_id
    )
    linked_result = await session.execute(
        select(
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
            WhatsAppBroadcastGroupModel.name,
        )
        .join(
            WhatsAppBroadcastGroupModel,
            WhatsAppBroadcastGroupModel.id
            == ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id,
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id
            == group.id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id
            == group.agency_id,
            WhatsAppBroadcastGroupModel.agency_id == group.agency_id,
        )
    )
    linked_broadcasts = {
        broadcast_id: broadcast_name
        for broadcast_id, broadcast_name in linked_result.all()
    }
    if (
        broadcast_id is not None
        and broadcast_id not in linked_broadcasts
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "The selected WhatsApp broadcast is not linked to this "
                "client group."
            ),
        )

    recipients: list[RecipientForComparison] = []
    if linked_broadcasts:
        recipient_result = await session.execute(
            select(WhatsAppBroadcastRecipientModel).where(
                WhatsAppBroadcastRecipientModel.agency_id
                == group.agency_id,
                WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(
                    list(linked_broadcasts)
                ),
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            )
        )
        recipients = [
            RecipientForComparison(
                id=recipient.id,
                broadcast_id=recipient.broadcast_group_id,
                broadcast_name=linked_broadcasts[
                    recipient.broadcast_group_id
                ],
                name=recipient.name,
                phone=recipient.normalized_phone_number,
                updated_at=recipient.created_at,
                imported_fields=dict(recipient.imported_fields or {}),
            )
            for recipient in recipient_result.scalars().all()
        ]

    submission_result = await session.execute(
        select(PassportSubmissionModel).where(
            PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.agency_id == group.agency_id,
            PassportSubmissionModel.status.in_(
                OFFICE_VISIBLE_PASSPORT_STATUS_VALUES
            ),
        )
    )
    submissions = [
        SubmissionForComparison(
            id=submission.id,
            name=submission.client_name,
            client_phone=submission.client_phone,
            family_head_phone=submission.family_head_phone,
            updated_at=submission.updated_at,
            client_email=submission.client_email,
            family_head_email=submission.family_head_email,
            confirmed_fields=dict(submission.confirmed_fields or {}),
            extracted_fields=dict(submission.extracted_fields or {}),
            staff_metadata=dict(submission.staff_metadata or {}),
        )
        for submission in submission_result.scalars().all()
    ]
    rows, counts = compare_group_submissions(recipients, submissions)
    if broadcast_id is not None:
        rows = [
            row for row in rows if broadcast_id in row.broadcast_ids
        ]
        counts = summarize_match_rows(rows)
    ordered_rows = filter_and_sort_match_rows(
        rows,
        status=match_status,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    total = len(ordered_rows)
    offset = (page - 1) * page_size
    page_rows = ordered_rows[offset : offset + page_size]
    return ClientGroupWhatsAppMatchesResponse(
        client_group_id=group.id,
        selected_broadcast_id=broadcast_id,
        linked_broadcast_count=len(linked_broadcasts),
        counts=WhatsAppSubmissionMatchCountsResponse(
            total_recipients=counts.total_recipients,
            submitted_count=counts.submitted_count,
            not_submitted_count=counts.not_submitted_count,
            multiple_submission_count=counts.multiple_submission_count,
            matched_submission_count=counts.matched_submission_count,
            needs_review_count=counts.needs_review_count,
            needs_review_submission_count=(
                counts.needs_review_submission_count
            ),
            unmatched_submission_count=counts.unmatched_submission_count,
        ),
        matches=[
            WhatsAppSubmissionMatchRowResponse(
                status=row.status,
                match_basis=row.match_basis,
                normalized_phone=row.normalized_phone,
                recipient_ids=list(row.recipient_ids),
                submission_ids=list(row.submission_ids),
                broadcast_ids=list(row.broadcast_ids),
                broadcast_names=list(row.broadcast_names),
                recipient_names=list(row.recipient_names),
                submission_names=list(row.submission_names),
                confidence=row.confidence,
                match_evidence=[
                    WhatsAppSubmissionMatchEvidenceResponse(
                        submission_id=evidence.submission_id,
                        kind=evidence.kind,
                        recipient_value=evidence.recipient_value,
                        submission_value=evidence.submission_value,
                        weight=evidence.weight,
                    )
                    for evidence in row.match_evidence
                ],
                candidate_submission_ids=list(
                    row.candidate_submission_ids
                ),
                recipient_fields=[
                    WhatsAppRecipientImportedFieldsResponse(
                        recipient_id=field_set.recipient_id,
                        fields=field_set.fields,
                    )
                    for field_set in row.recipient_fields
                ],
                updated_at=row.updated_at,
            )
            for row in page_rows
        ],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=ceil(total / page_size) if total else 0,
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

    if request.whatsapp_broadcast_group_ids is not None:
        _require_whatsapp_broadcast_access(current_user)

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
        agent_employee_code_enabled=request.agent_employee_code_enabled,
        meal_preference_enabled=request.meal_preference_enabled,
        require_selfie=request.require_selfie,
        allow_files_from_device=request.allow_files_from_device,
        ask_nearest_domestic_airport=request.ask_nearest_domestic_airport,
        relation_with_qualifier_enabled=request.relation_with_qualifier_enabled,
        notes=request.notes,
    )
    await repo.update(group)
    if request.whatsapp_broadcast_group_ids is not None:
        summaries, previous_ids, changed = await _replace_whatsapp_links(
            session,
            group_id=group.id,
            agency_id=group.agency_id,
            created_by_user_id=current_user.id,
            broadcast_ids=request.whatsapp_broadcast_group_ids,
        )
        await AuditLogRepository(session).record(
            action="client_group_whatsapp_links_replaced",
            entity_type="client_group",
            entity_id=str(group.id),
            agency_id=group.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "changed": changed,
                "previous_broadcast_count": len(previous_ids),
                "broadcast_count": len(summaries),
                "whatsapp_broadcast_group_ids": [
                    str(summary.id) for summary in summaries
                ],
            },
        )
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
    crop_repository = PassportImageCropRepository(session)
    storage_keys.extend(await crop_repository.derived_storage_keys(submission_ids))
    storage_keys.extend(await crop_repository.edit_storage_keys(submission_ids))

    await session.execute(delete(ManagerGroupAccessModel).where(ManagerGroupAccessModel.group_id == link_id))
    await session.execute(
        delete(ClientGroupWhatsAppBroadcastLinkModel).where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id
            == link_id
        )
    )
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
