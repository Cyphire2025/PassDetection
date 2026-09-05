"""
Upload Links Routes — /api/v1/upload-links
==========================================
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
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
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.application.dtos.client_group_dtos import (
    CreateClientGroupInputDTO,
    client_group_output_from_entity,
)
from app.application.mobile.passenger_change_propagation import (
    reconcile_mobile_passenger_access_for_group,
)
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.security.destructive_mutation_policy import (
    DestructiveMutationPolicy,
    record_destructive_failure,
)
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
    SubmissionMatchRow,
    compare_group_submissions,
    filter_and_sort_match_rows,
    summarize_match_rows,
)
from app.application.use_cases.whatsapp.recipient_capacity import (
    MAX_WHATSAPP_RECIPIENTS,
    WhatsAppRecipientCapacityExceeded,
)
from app.core.security.upload_session import is_valid_upload_session_id
from app.domain.entities.entities import (
    OFFICE_VISIBLE_PASSPORT_STATUS_VALUES,
    ClientGroup,
    User,
    UserRole,
)
from app.domain.exceptions.exceptions import (
    AuthorizationError,
    ConflictError,
    EntityNotFoundError,
    PassDetectionError,
)
from app.infrastructure.database.models import (
    ClientGroupModel,
    ClientGroupWhatsAppBroadcastLinkModel,
    ManagerGroupAccessModel,
    NotificationModel,
    PassengerQRTokenModel,
    PassportProcessingJobModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    PlatformSettingModel,
    QualifierSelectionModel,
    StorageCleanupJobModel,
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.storage_cleanup import stage_storage_cleanup_jobs
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
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    lock_whatsapp_broadcast_groups,
    suppress_active_replacement_recipients,
)
from app.infrastructure.repositories.passport_whatsapp_matching_repository import (
    load_unresolved_passport_whatsapp_match_context,
)
from app.infrastructure.repositories.platform_policy_repository import (
    PlatformPolicyRepository,
)
from app.infrastructure.repositories.qualifier_selection_repository import (
    QualifierSelectionRepository,
)
from app.infrastructure.repositories.whatsapp_recipient_capacity_repository import (
    require_locked_broadcast_recipient_capacity,
)
from app.infrastructure.storage.passport_object_keys import passport_storage_keys
from app.infrastructure.whatsapp.private_delivery_policy import (
    PrivateDeliveryMutationBlocked,
    prepare_private_delivery_identity_mutation,
)
from app.presentation.api.v1.routes import (
    client_group_whatsapp_match_support as _whatsapp_match_support,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import qr_expires_at_for_group
from app.presentation.api.v1.schemas.client_group_schemas import (
    ClientGroupResponse,
    ClientGroupWhatsAppLinksResponse,
    ClientGroupWhatsAppMatchesResponse,
    CreateClientGroupRequest,
    CreateQualifierSelectionRequest,
    CreateQualifierSelectionResponse,
    PassportRosterResolutionResponse,
    PublicFlowTelemetryRequest,
    QualifierSelectionStateResponse,
    RejectUnidentifiedUploadRequest,
    ReplacementCandidateListResponse,
    ReplacementCandidateResponse,
    ReplaceWhatsAppBroadcastLinksRequest,
    ResolveUnidentifiedReplacementRequest,
    UpdateClientGroupRequest,
    WhatsAppBroadcastSummaryResponse,
)
from app.presentation.dependencies.auth import (
    WHATSAPP_BROADCAST_ROLES,
    get_current_active_user,
    require_recent_mfa,
)
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()

_CLIENT_GROUP_CREATION_ROLES = {
    UserRole.SUPER_ADMIN,
    UserRole.AGENCY_ADMIN,
    UserRole.AGENCY_MANAGER,
    UserRole.AGENCY_STAFF,
}
_PLATFORM_SETTINGS_KEY = "global"

_stored_uuid_list = _whatsapp_match_support.stored_uuid_list
_roster_resolution_response = _whatsapp_match_support.roster_resolution_response


# ── Dependency Factories ──────────────────────────────────────────────────


def _get_create_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> CreateClientGroupUseCase:
    return CreateClientGroupUseCase(
        ClientGroupRepository(session),
        PlatformPolicyRepository(session),
    )


def _get_get_by_token_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> GetClientGroupByTokenUseCase:
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


def _get_revoke_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> RevokeClientGroupUseCase:
    return RevokeClientGroupUseCase(
        ClientGroupRepository(session),
        PlatformPolicyRepository(session),
    )


def _get_delete_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> DeleteClientGroupUseCase:
    return DeleteClientGroupUseCase(
        ClientGroupRepository(session),
        PlatformPolicyRepository(session),
    )


def _get_restore_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> RestoreClientGroupUseCase:
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
            func.count(WhatsAppBroadcastRecipientModel.id).label("recipient_count"),
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
        stmt = stmt.where(WhatsAppBroadcastGroupModel.id.in_(broadcast_ids))
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
            detail=("One or more WhatsApp broadcast groups are unavailable for this agency."),
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
            func.count(WhatsAppBroadcastRecipientModel.id).label("recipient_count"),
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
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id.in_(client_group_ids),
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
    summaries: dict[uuid.UUID, list[WhatsAppBroadcastSummaryResponse]] = {
        group_id: [] for group_id in client_group_ids
    }
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
    # Serialize link-set edits for this passport group. Broadcast rows are then
    # locked in the same stable order used by replacement creation so an
    # unlink cannot pass the active-replacement check concurrently.
    await session.execute(
        select(ClientGroupModel.id)
        .where(
            ClientGroupModel.id == group_id,
            ClientGroupModel.agency_id == agency_id,
        )
        .with_for_update()
    )
    existing_result = await session.execute(
        select(ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id).where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group_id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
        )
    )
    previous_ids = sorted(set(existing_result.scalars().all()), key=str)
    requested_ids = sorted(set(broadcast_ids), key=str)
    affected_broadcast_ids = sorted(
        set(previous_ids).union(requested_ids),
        key=str,
    )
    locked_broadcast_ids = await lock_whatsapp_broadcast_groups(
        session,
        agency_id=agency_id,
        broadcast_group_ids=affected_broadcast_ids,
    )
    if set(locked_broadcast_ids) != set(affected_broadcast_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "One or more WhatsApp broadcast groups changed while links "
                "were being updated. Refresh and try again."
            ),
        )
    summaries = await _validate_broadcast_ids(
        session,
        agency_id=agency_id,
        broadcast_ids=requested_ids,
    )
    changed = previous_ids != requested_ids
    if changed:
        try:
            await prepare_private_delivery_identity_mutation(
                session,
                agency_id=agency_id,
                group_id=group_id,
                cancel_queued=True,
                cancellation_reason=(
                    "WhatsApp broadcast links changed before private delivery"
                ),
            )
        except PrivateDeliveryMutationBlocked as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        removed_broadcast_ids = set(previous_ids) - set(requested_ids)
        if removed_broadcast_ids:
            active_replacement_result = await session.execute(
                select(PassportRosterResolutionModel.id)
                .join(
                    WhatsAppBroadcastRecipientModel,
                    WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id
                    == PassportRosterResolutionModel.id,
                )
                .where(
                    PassportRosterResolutionModel.client_group_id == group_id,
                    PassportRosterResolutionModel.agency_id == agency_id,
                    PassportRosterResolutionModel.status == "active",
                    PassportRosterResolutionModel.resolution_type == "replacement",
                    WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(removed_broadcast_ids),
                )
                .limit(1)
            )
            if active_replacement_result.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "A broadcast cannot be unlinked while it contains a "
                        "person marked as replaced in this passport group. "
                        "Restore the replacement first."
                    ),
                )
        await session.execute(
            delete(ClientGroupWhatsAppBroadcastLinkModel).where(
                ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group_id,
                ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
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
    if requested_ids:
        await suppress_active_replacement_recipients(
            session,
            agency_id=agency_id,
            broadcast_group_ids=requested_ids,
            now=datetime.now(tz=UTC),
        )
        await session.flush()
        summaries = await _validate_broadcast_ids(
            session,
            agency_id=agency_id,
            broadcast_ids=requested_ids,
        )
    if changed:
        await reconcile_mobile_passenger_access_for_group(
            session,
            agency_id=agency_id,
            group_id=group_id,
            actor_user_id=created_by_user_id,
        )
    return summaries, previous_ids, changed


async def _require_client_group_creation_access(
    user: User,
    session: AsyncSession,
) -> None:
    """Apply the server-authoritative role and manager feature policy."""

    if user.role not in _CLIENT_GROUP_CREATION_ROLES:
        raise AuthorizationError("This account cannot create upload links")
    if user.role != UserRole.AGENCY_MANAGER:
        return

    result = await session.execute(
        select(PlatformSettingModel.value).where(
            PlatformSettingModel.key == _PLATFORM_SETTINGS_KEY
        )
    )
    values = result.scalar_one_or_none() or {}
    if values.get("allow_manager_group_creation", True) is not True:
        raise AuthorizationError(
            "Manager upload-link creation is disabled by platform settings"
        )


async def _require_managed_group(
    session: AsyncSession,
    current_user: User,
    link_id: uuid.UUID,
) -> ClientGroup:
    group = await ClientGroupRepository(session).get_by_id(link_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client group was not found",
        )
    try:
        await AuthorizationPolicy(session).require_manage_group(current_user, group)
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
) -> ClientGroup:
    group = await ClientGroupRepository(session).get_by_id(link_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client group was not found",
        )
    try:
        await AuthorizationPolicy(session).require_view_group(current_user, group)
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
        select(WhatsAppBroadcastRecipientModel.normalized_phone_number)
        .join(
            ClientGroupWhatsAppBroadcastLinkModel,
            ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id
            == WhatsAppBroadcastRecipientModel.broadcast_group_id,
        )
        .where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group_id,
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


def _require_matching_roster_resolution_replay(
    resolution: PassportRosterResolutionModel,
    *,
    client_group_id: uuid.UUID,
    submission_id: uuid.UUID,
    resolution_type: Literal["replacement", "rejected"],
    broadcast_recipient_id: uuid.UUID | None,
    conflict_detail: str,
) -> PassportRosterResolutionModel:
    if (
        resolution.client_group_id != client_group_id
        or resolution.submission_id != submission_id
        or resolution.resolution_type != resolution_type
        or resolution.broadcast_recipient_id != broadcast_recipient_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=conflict_detail,
        )
    return resolution


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
            detail="User must be associated with an agency to create upload links.",
        )

    await _require_client_group_creation_access(current_user, session)

    if request.whatsapp_broadcast_group_ids:
        _require_whatsapp_broadcast_access(current_user)

    dto = CreateClientGroupInputDTO(
        name=request.name,
        destination=request.destination,
        travel_date=request.travel_date,
        return_date=request.return_date,
        timezone=request.timezone,
        package_name=request.package_name,
        departure_cities=request.departure_cities,
        base_city_enabled=request.base_city_enabled,
        nearest_international_airport_enabled=request.nearest_international_airport_enabled,
        staff_code_enabled=request.staff_code_enabled,
        agent_employee_code_enabled=request.agent_employee_code_enabled,
        meal_preference_enabled=request.meal_preference_enabled,
        require_selfie=request.require_selfie,
        upload_configuration=(request.upload_configuration.model_dump(mode="json") if request.upload_configuration is not None else None),
        allow_files_from_device=request.allow_files_from_device,
        ask_nearest_domestic_airport=request.ask_nearest_domestic_airport,
        relation_with_qualifier_enabled=request.relation_with_qualifier_enabled,
        designation_enabled=request.designation_enabled,
        agency_dealership_name_enabled=request.agency_dealership_name_enabled,
        custom_questions=[
            question.model_dump(mode="json") for question in request.custom_questions
        ],
        custom_details=[detail.model_dump(mode="json") for detail in request.custom_details],
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
            "whatsapp_broadcast_group_ids": [str(summary.id) for summary in linked],
        },
    )
    return ClientGroupResponse.model_validate(result)


async def _linked_broadcast_names_for_group(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
) -> dict[uuid.UUID, str]:
    result = await session.execute(
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
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group_id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == agency_id,
            WhatsAppBroadcastGroupModel.agency_id == agency_id,
        )
    )
    return {broadcast_id: broadcast_name for broadcast_id, broadcast_name in result.all()}


async def _current_unresolved_match_context(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
) -> tuple[
    dict[uuid.UUID, str],
    list[WhatsAppBroadcastRecipientModel],
    list[PassportSubmissionModel],
    list[SubmissionMatchRow],
]:
    return await load_unresolved_passport_whatsapp_match_context(
        session,
        group_id=group_id,
        agency_id=agency_id,
    )


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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super admins can view deleted group data",
        )

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
    group = await _require_managed_group(session, current_user, link_id)
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
    use_case: GetClientGroupByTokenUseCase = Depends(_get_get_by_token_use_case),
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
    use_case: CreateQualifierSelectionUseCase = Depends(_get_create_qualifier_selection_use_case),
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
    use_case: GetQualifierSelectionUseCase = Depends(_get_qualifier_selection_use_case),
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
    group = await _require_viewable_group(session, current_user, link_id)
    can_manage = await AuthorizationPolicy(session).can_manage_group(current_user, group)
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
    _csrf: None = Depends(require_cookie_csrf),
    session: AsyncSession = Depends(get_db_session),
) -> ClientGroupWhatsAppLinksResponse:
    _require_whatsapp_broadcast_access(current_user)
    group = await _require_managed_group(session, current_user, link_id)
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
            "whatsapp_broadcast_group_ids": [str(summary.id) for summary in summaries],
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
        "replacement",
        "rejected_upload",
    ] = Query(default="all", alias="status"),
    sort_by: Literal["name", "phone", "status", "broadcast", "updated_at"] = "name",
    sort_order: Literal["asc", "desc"] = "asc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=200),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ClientGroupWhatsAppMatchesResponse:
    _require_whatsapp_broadcast_access(current_user)
    group = await _require_viewable_group(session, current_user, link_id)
    linked_broadcasts = await _linked_broadcast_names_for_group(
        session,
        group_id=group.id,
        agency_id=group.agency_id,
    )
    if broadcast_id is not None and broadcast_id not in linked_broadcasts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=("The selected WhatsApp broadcast is not linked to this client group."),
        )

    resolution_result = await session.execute(
        select(PassportRosterResolutionModel).where(
            PassportRosterResolutionModel.client_group_id == group.id,
            PassportRosterResolutionModel.agency_id == group.agency_id,
            PassportRosterResolutionModel.status == "active",
        )
    )
    active_resolutions = list(resolution_result.scalars().all())
    suppressed_recipient_ids = {
        recipient_id
        for resolution in active_resolutions
        for recipient_id in _stored_uuid_list(resolution.suppressed_recipient_ids)
    }
    excluded_submission_ids = {
        submission_id
        for resolution in active_resolutions
        for submission_id in (
            [resolution.submission_id] + _stored_uuid_list(resolution.excluded_submission_ids)
        )
    }

    recipient_models: list[WhatsAppBroadcastRecipientModel] = []
    if linked_broadcasts:
        recipient_visibility = (
            or_(
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
                WhatsAppBroadcastRecipientModel.id.in_(suppressed_recipient_ids),
            )
            if suppressed_recipient_ids
            else WhatsAppBroadcastRecipientModel.removed_at.is_(None)
        )
        recipient_result = await session.execute(
            select(WhatsAppBroadcastRecipientModel).where(
                WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
                WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(list(linked_broadcasts)),
                recipient_visibility,
            )
        )
        recipient_models = list(recipient_result.scalars().all())
    recipient_model_by_id = {recipient.id: recipient for recipient in recipient_models}
    recipients = [
        RecipientForComparison(
            id=recipient.id,
            broadcast_id=recipient.broadcast_group_id,
            broadcast_name=linked_broadcasts[recipient.broadcast_group_id],
            name=recipient.name,
            phone=recipient.normalized_phone_number,
            updated_at=recipient.created_at,
            imported_fields=dict(recipient.imported_fields or {}),
        )
        for recipient in recipient_models
        if recipient.removed_at is None and recipient.id not in suppressed_recipient_ids
    ]

    submission_result = await session.execute(
        select(PassportSubmissionModel).where(
            PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.agency_id == group.agency_id,
            PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
        )
    )
    submission_models = list(submission_result.scalars().all())
    submission_model_by_id = {submission.id: submission for submission in submission_models}
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
        for submission in submission_models
        if submission.id not in excluded_submission_ids
    ]
    rows, _ = compare_group_submissions(recipients, submissions)
    rows = _whatsapp_match_support.include_active_resolution_rows(
        rows,
        active_resolutions=active_resolutions,
        submissions_by_id=submission_model_by_id,
        recipients_by_id=recipient_model_by_id,
        linked_broadcasts=linked_broadcasts,
    )
    counts = summarize_match_rows(rows)
    if broadcast_id is not None:
        rows = [row for row in rows if broadcast_id in row.broadcast_ids]
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
    return _whatsapp_match_support.build_whatsapp_matches_response(
        client_group_id=group.id,
        selected_broadcast_id=broadcast_id,
        linked_broadcast_count=len(linked_broadcasts),
        counts=counts,
        page_rows=page_rows,
        submissions_by_id=submission_model_by_id,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{link_id}/replacement-candidates",
    response_model=ReplacementCandidateListResponse,
    status_code=status.HTTP_200_OK,
    summary="List active linked recipients that an unidentified upload can replace",
)
async def list_replacement_candidates(
    link_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ReplacementCandidateListResponse:
    _require_whatsapp_broadcast_access(current_user)
    group = await _require_managed_group(session, current_user, link_id)
    linked_broadcasts = await _linked_broadcast_names_for_group(
        session,
        group_id=group.id,
        agency_id=group.agency_id,
    )
    recipient_models: list[WhatsAppBroadcastRecipientModel] = []
    if linked_broadcasts:
        result = await session.execute(
            select(WhatsAppBroadcastRecipientModel).where(
                WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
                WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(list(linked_broadcasts)),
                WhatsAppBroadcastRecipientModel.removed_at.is_(None),
                WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id.is_(None),
            )
        )
        recipient_models = list(result.scalars().all())

    grouped: dict[str, list[WhatsAppBroadcastRecipientModel]] = {}
    for recipient in recipient_models:
        normalized = normalize_whatsapp_phone(recipient.normalized_phone_number)
        if normalized:
            grouped.setdefault(normalized, []).append(recipient)
    items: list[ReplacementCandidateResponse] = []
    for phone, logical_recipients in grouped.items():
        ordered = sorted(
            logical_recipients,
            key=lambda recipient: (
                linked_broadcasts.get(recipient.broadcast_group_id, "").casefold(),
                str(recipient.id),
            ),
        )
        first = ordered[0]
        items.append(
            ReplacementCandidateResponse(
                recipient_id=first.id,
                recipient_ids=[recipient.id for recipient in ordered],
                name=next(
                    (recipient.name for recipient in ordered if recipient.name),
                    None,
                ),
                phone=phone,
                broadcast_ids=list(
                    dict.fromkeys(recipient.broadcast_group_id for recipient in ordered)
                ),
                broadcast_names=list(
                    dict.fromkeys(
                        linked_broadcasts[recipient.broadcast_group_id] for recipient in ordered
                    )
                ),
                imported_fields=dict(first.imported_fields or {}),
            )
        )
    items.sort(
        key=lambda item: (
            (item.name or "").casefold(),
            item.phone,
            str(item.recipient_id),
        )
    )
    return ReplacementCandidateListResponse(
        client_group_id=group.id,
        items=items,
    )


@router.post(
    "/{link_id}/unidentified/{submission_id}/replacement",
    response_model=PassportRosterResolutionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Mark an unidentified passport upload as a recipient replacement",
)
async def resolve_unidentified_as_replacement(
    link_id: uuid.UUID,
    submission_id: uuid.UUID,
    body: ResolveUnidentifiedReplacementRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_cookie_csrf),
) -> PassportRosterResolutionResponse:
    _require_whatsapp_broadcast_access(current_user)
    group = await _require_managed_group(session, current_user, link_id)
    existing_result = await session.execute(
        select(PassportRosterResolutionModel).where(
            PassportRosterResolutionModel.client_group_id == group.id,
            PassportRosterResolutionModel.request_id == body.request_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        replay = _require_matching_roster_resolution_replay(
            existing,
            client_group_id=group.id,
            submission_id=submission_id,
            resolution_type="replacement",
            broadcast_recipient_id=body.recipient_id,
            conflict_detail="That replacement request ID was already used.",
        )
        return _roster_resolution_response(replay)

    submission_result = await session.execute(
        select(PassportSubmissionModel)
        .where(
            PassportSubmissionModel.id == submission_id,
            PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.agency_id == group.agency_id,
            PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
        )
        .with_for_update()
    )
    submission = submission_result.scalar_one_or_none()
    if submission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passport upload was not found in this group.",
        )

    (
        linked_broadcasts,
        _recipient_models,
        _submission_models,
        match_rows,
    ) = await _current_unresolved_match_context(
        session,
        group_id=group.id,
        agency_id=group.agency_id,
    )
    unidentified_row = next(
        (
            row
            for row in match_rows
            if row.status == "unmatched_submission" and submission_id in row.submission_ids
        ),
        None,
    )
    if unidentified_row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This upload is no longer unidentified. Refresh the tracking "
                "page before choosing a replacement."
            ),
        )

    locked_broadcast_ids = await lock_whatsapp_broadcast_groups(
        session,
        agency_id=group.agency_id,
        broadcast_group_ids=list(linked_broadcasts),
    )
    if set(locked_broadcast_ids) != set(linked_broadcasts):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The linked WhatsApp broadcasts changed. Refresh the tracking "
                "page before choosing a replacement."
            ),
        )
    live_links_result = await session.execute(
        select(ClientGroupWhatsAppBroadcastLinkModel.broadcast_group_id).where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == group.id,
            ClientGroupWhatsAppBroadcastLinkModel.agency_id == group.agency_id,
        )
    )
    live_linked_broadcast_ids = sorted(
        set(live_links_result.scalars().all()),
        key=str,
    )
    if set(live_linked_broadcast_ids) != set(linked_broadcasts):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The linked WhatsApp broadcasts changed. Refresh the tracking "
                "page before choosing a replacement."
            ),
        )
    selected_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.id == body.recipient_id,
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            WhatsAppBroadcastRecipientModel.broadcast_group_id.in_(
                live_linked_broadcast_ids or [uuid.uuid4()]
            ),
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id.is_(None),
        )
        .with_for_update()
    )
    selected_recipient = selected_result.scalar_one_or_none()
    if selected_recipient is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The selected recipient is no longer available for replacement.",
        )
    recipient_row = next(
        (row for row in match_rows if body.recipient_id in row.recipient_ids),
        None,
    )
    if recipient_row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The selected recipient could not be resolved in this group.",
        )

    suppressed_ids = list(dict.fromkeys(recipient_row.recipient_ids))
    excluded_submission_ids = list(
        dict.fromkeys(
            (
                *recipient_row.submission_ids,
                *recipient_row.candidate_submission_ids,
            )
        )
    )
    locked_recipients_result = await session.execute(
        select(WhatsAppBroadcastRecipientModel)
        .where(
            WhatsAppBroadcastRecipientModel.id.in_(suppressed_ids),
            WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            WhatsAppBroadcastRecipientModel.removed_at.is_(None),
            WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id.is_(None),
        )
        .with_for_update()
    )
    locked_recipients = list(locked_recipients_result.scalars().all())
    if {recipient.id for recipient in locked_recipients} != set(suppressed_ids):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="One of the linked recipient records changed. Refresh and try again.",
        )

    now = datetime.now(tz=UTC)
    resolution = PassportRosterResolutionModel(
        id=uuid.uuid4(),
        agency_id=group.agency_id,
        client_group_id=group.id,
        submission_id=submission.id,
        broadcast_recipient_id=selected_recipient.id,
        replaced_recipient_normalized_phone=selected_recipient.normalized_phone_number,
        original_recipient_name=selected_recipient.name,
        original_recipient_phone=selected_recipient.phone_number,
        original_recipient_imported_fields=dict(selected_recipient.imported_fields or {}),
        resolution_type="replacement",
        request_id=body.request_id,
        suppressed_recipient_ids=[str(recipient_id) for recipient_id in suppressed_ids],
        excluded_submission_ids=[
            str(original_submission_id) for original_submission_id in excluded_submission_ids
        ],
        status="active",
        resolved_by_user_id=current_user.id,
        created_at=now,
    )
    try:
        async with session.begin_nested():
            session.add(resolution)
            for recipient in locked_recipients:
                recipient.removed_at = now
                recipient.suppressed_by_roster_resolution_id = resolution.id
            await session.execute(
                update(WhatsAppMessageLogModel)
                .where(
                    WhatsAppMessageLogModel.recipient_id.in_(suppressed_ids),
                    WhatsAppMessageLogModel.status == "queued",
                )
                .values(
                    status="failed",
                    status_updated_at=now,
                    error_message=("Recipient replaced in linked passport group before delivery"),
                )
                .execution_options(synchronize_session=False)
            )
            await session.execute(
                update(WhatsAppRecipientMessageStateModel)
                .where(
                    WhatsAppRecipientMessageStateModel.recipient_id.in_(suppressed_ids),
                    WhatsAppRecipientMessageStateModel.status == "queued",
                )
                .values(
                    status="failed",
                    batch_id=None,
                    status_updated_at=now,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
            await session.execute(
                update(WhatsAppBroadcastGroupModel)
                .where(
                    WhatsAppBroadcastGroupModel.id.in_(
                        list({recipient.broadcast_group_id for recipient in locked_recipients})
                    )
                )
                .values(updated_at=now)
            )
            await session.flush()
            await suppress_active_replacement_recipients(
                session,
                agency_id=group.agency_id,
                broadcast_group_ids=list(linked_broadcasts),
                now=now,
            )
            await session.flush()
    except IntegrityError:
        retry_result = await session.execute(
            select(PassportRosterResolutionModel).where(
                PassportRosterResolutionModel.client_group_id == group.id,
                PassportRosterResolutionModel.request_id == body.request_id,
            )
        )
        retry = retry_result.scalar_one_or_none()
        if retry is not None:
            replay = _require_matching_roster_resolution_replay(
                retry,
                client_group_id=group.id,
                submission_id=submission_id,
                resolution_type="replacement",
                broadcast_recipient_id=body.recipient_id,
                conflict_detail="That replacement request ID was already used.",
            )
            return _roster_resolution_response(replay)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This upload or recipient was resolved by another request. "
                "Refresh the tracking page."
            ),
        )

    await reconcile_mobile_passenger_access_for_group(
        session,
        agency_id=group.agency_id,
        group_id=group.id,
        actor_user_id=current_user.id,
    )
    await AuditLogRepository(session).record(
        action="passport_unidentified_marked_replacement",
        entity_type="passport_roster_resolution",
        entity_id=str(resolution.id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "client_group_id": str(group.id),
            "replacement_submission_id": str(submission.id),
            "selected_recipient_id": str(selected_recipient.id),
            "suppressed_recipient_ids": [str(recipient_id) for recipient_id in suppressed_ids],
            "excluded_submission_ids": list(resolution.excluded_submission_ids),
        },
    )
    return _roster_resolution_response(resolution)


@router.post(
    "/{link_id}/unidentified/{submission_id}/reject",
    response_model=PassportRosterResolutionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Reject an unidentified passport upload from the active roster",
)
async def reject_unidentified_upload(
    link_id: uuid.UUID,
    submission_id: uuid.UUID,
    body: RejectUnidentifiedUploadRequest,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_cookie_csrf),
) -> PassportRosterResolutionResponse:
    _require_whatsapp_broadcast_access(current_user)
    group = await _require_managed_group(session, current_user, link_id)
    existing_result = await session.execute(
        select(PassportRosterResolutionModel).where(
            PassportRosterResolutionModel.client_group_id == group.id,
            PassportRosterResolutionModel.request_id == body.request_id,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        replay = _require_matching_roster_resolution_replay(
            existing,
            client_group_id=group.id,
            submission_id=submission_id,
            resolution_type="rejected",
            broadcast_recipient_id=None,
            conflict_detail="That rejection request ID was already used.",
        )
        return _roster_resolution_response(replay)

    submission_result = await session.execute(
        select(PassportSubmissionModel)
        .where(
            PassportSubmissionModel.id == submission_id,
            PassportSubmissionModel.group_id == group.id,
            PassportSubmissionModel.agency_id == group.agency_id,
            PassportSubmissionModel.status.in_(OFFICE_VISIBLE_PASSPORT_STATUS_VALUES),
        )
        .with_for_update()
    )
    submission = submission_result.scalar_one_or_none()
    if submission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Passport upload was not found in this group.",
        )
    _linked, _recipients, _submissions, match_rows = await _current_unresolved_match_context(
        session,
        group_id=group.id,
        agency_id=group.agency_id,
    )
    if not any(
        row.status == "unmatched_submission" and submission_id in row.submission_ids
        for row in match_rows
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This upload is no longer unidentified. Refresh the tracking "
                "page before rejecting it."
            ),
        )
    resolution = PassportRosterResolutionModel(
        id=uuid.uuid4(),
        agency_id=group.agency_id,
        client_group_id=group.id,
        submission_id=submission.id,
        broadcast_recipient_id=None,
        resolution_type="rejected",
        request_id=body.request_id,
        suppressed_recipient_ids=[],
        excluded_submission_ids=[],
        status="active",
        resolved_by_user_id=current_user.id,
        created_at=datetime.now(tz=UTC),
    )
    try:
        async with session.begin_nested():
            session.add(resolution)
            await session.flush()
    except IntegrityError:
        retry_result = await session.execute(
            select(PassportRosterResolutionModel).where(
                PassportRosterResolutionModel.client_group_id == group.id,
                PassportRosterResolutionModel.request_id == body.request_id,
            )
        )
        retry = retry_result.scalar_one_or_none()
        if retry is not None:
            replay = _require_matching_roster_resolution_replay(
                retry,
                client_group_id=group.id,
                submission_id=submission_id,
                resolution_type="rejected",
                broadcast_recipient_id=None,
                conflict_detail="That rejection request ID was already used.",
            )
            return _roster_resolution_response(replay)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This upload was resolved by another request. Refresh the page.",
        )
    await reconcile_mobile_passenger_access_for_group(
        session,
        agency_id=group.agency_id,
        group_id=group.id,
        actor_user_id=current_user.id,
    )
    await AuditLogRepository(session).record(
        action="passport_unidentified_rejected",
        entity_type="passport_roster_resolution",
        entity_id=str(resolution.id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "client_group_id": str(group.id),
            "submission_id": str(submission.id),
        },
    )
    return _roster_resolution_response(resolution)


@router.post(
    "/{link_id}/roster-resolutions/{resolution_id}/restore",
    response_model=PassportRosterResolutionResponse,
    status_code=status.HTTP_200_OK,
    summary="Restore a replaced recipient or rejected unidentified upload",
)
async def restore_roster_resolution(
    link_id: uuid.UUID,
    resolution_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
    _csrf: None = Depends(require_cookie_csrf),
) -> PassportRosterResolutionResponse:
    _require_whatsapp_broadcast_access(current_user)
    group = await _require_managed_group(session, current_user, link_id)
    preliminary_result = await session.execute(
        select(PassportRosterResolutionModel).where(
            PassportRosterResolutionModel.id == resolution_id,
            PassportRosterResolutionModel.client_group_id == group.id,
            PassportRosterResolutionModel.agency_id == group.agency_id,
        )
    )
    preliminary_resolution = preliminary_result.scalar_one_or_none()
    if preliminary_resolution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Roster resolution was not found.",
        )
    if preliminary_resolution.status == "restored":
        return _roster_resolution_response(preliminary_resolution)

    broadcast_ids: list[uuid.UUID] = []
    locked_broadcast_ids: list[uuid.UUID] = []
    if preliminary_resolution.resolution_type == "replacement":
        broadcast_ids_result = await session.execute(
            select(WhatsAppBroadcastRecipientModel.broadcast_group_id).where(
                WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id
                == preliminary_resolution.id,
                WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            )
        )
        broadcast_ids = list(dict.fromkeys(broadcast_ids_result.scalars().all()))
        locked_broadcast_ids = await lock_whatsapp_broadcast_groups(
            session,
            agency_id=group.agency_id,
            broadcast_group_ids=broadcast_ids,
        )

    # Every path that can suppress or reactivate recipients takes broadcast
    # locks before the resolution lock. Keep the same global order here.
    result = await session.execute(
        select(PassportRosterResolutionModel)
        .where(
            PassportRosterResolutionModel.id == resolution_id,
            PassportRosterResolutionModel.client_group_id == group.id,
            PassportRosterResolutionModel.agency_id == group.agency_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    resolution = result.scalar_one_or_none()
    if resolution is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Roster resolution was not found.",
        )
    if resolution.status == "restored":
        return _roster_resolution_response(resolution)

    now = datetime.now(tz=UTC)
    restored_recipient_ids: list[uuid.UUID] = []
    if resolution.resolution_type == "replacement":
        recipients_result = await session.execute(
            select(WhatsAppBroadcastRecipientModel)
            .where(
                WhatsAppBroadcastRecipientModel.suppressed_by_roster_resolution_id == resolution.id,
                WhatsAppBroadcastRecipientModel.agency_id == group.agency_id,
            )
            .with_for_update()
        )
        recipients = list(recipients_result.scalars().all())
        live_broadcast_ids = {recipient.broadcast_group_id for recipient in recipients}
        if not live_broadcast_ids.issubset(set(locked_broadcast_ids)):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "The linked WhatsApp recipients changed while the replacement "
                    "was being restored. Refresh and try again."
                ),
            )
        activating_by_broadcast: dict[uuid.UUID, int] = {}
        for recipient in recipients:
            if recipient.removed_at is not None:
                activating_by_broadcast[recipient.broadcast_group_id] = (
                    activating_by_broadcast.get(recipient.broadcast_group_id, 0) + 1
                )
        try:
            await require_locked_broadcast_recipient_capacity(
                session,
                agency_id=group.agency_id,
                locked_broadcast_ids=locked_broadcast_ids,
                activating_by_broadcast=activating_by_broadcast,
            )
        except WhatsAppRecipientCapacityExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Restoring this replacement would exceed the maximum of "
                    f"{MAX_WHATSAPP_RECIPIENTS} recipients in a WhatsApp list."
                ),
            ) from exc
        for recipient in recipients:
            recipient.removed_at = None
            recipient.suppressed_by_roster_resolution_id = None
            restored_recipient_ids.append(recipient.id)
        if recipients:
            await session.execute(
                update(WhatsAppBroadcastGroupModel)
                .where(
                    WhatsAppBroadcastGroupModel.id.in_(
                        list({recipient.broadcast_group_id for recipient in recipients})
                    )
                )
                .values(updated_at=now)
            )
    resolution.status = "restored"
    resolution.restored_by_user_id = current_user.id
    resolution.restored_at = now
    await session.flush()
    if resolution.resolution_type == "replacement":
        await suppress_active_replacement_recipients(
            session,
            agency_id=group.agency_id,
            broadcast_group_ids=broadcast_ids,
            now=now,
        )
        await session.flush()
    await reconcile_mobile_passenger_access_for_group(
        session,
        agency_id=group.agency_id,
        group_id=group.id,
        actor_user_id=current_user.id,
    )
    await AuditLogRepository(session).record(
        action="passport_roster_resolution_restored",
        entity_type="passport_roster_resolution",
        entity_id=str(resolution.id),
        agency_id=group.agency_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "client_group_id": str(group.id),
            "submission_id": str(resolution.submission_id),
            "resolution_type": resolution.resolution_type,
            "restored_recipient_ids": [
                str(recipient_id) for recipient_id in restored_recipient_ids
            ],
        },
    )
    return _roster_resolution_response(resolution)


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
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    group = await ClientGroupRepository(session).get_by_id(link_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found"
        )
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    repo = ClientGroupRepository(session)
    group = await repo.get_by_id(link_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found"
        )
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
        timezone=request.timezone or group.timezone,
        package_name=request.package_name,
        departure_cities=request.departure_cities,
        base_city_enabled=request.base_city_enabled,
        nearest_international_airport_enabled=request.nearest_international_airport_enabled,
        staff_code_enabled=request.staff_code_enabled,
        agent_employee_code_enabled=request.agent_employee_code_enabled,
        meal_preference_enabled=request.meal_preference_enabled,
        require_selfie=request.require_selfie,
        upload_configuration=(request.upload_configuration.model_dump(mode="json") if request.upload_configuration is not None else None),
        allow_files_from_device=request.allow_files_from_device,
        ask_nearest_domestic_airport=request.ask_nearest_domestic_airport,
        relation_with_qualifier_enabled=request.relation_with_qualifier_enabled,
        designation_enabled=request.designation_enabled,
        agency_dealership_name_enabled=request.agency_dealership_name_enabled,
        custom_questions=(
            [question.model_dump(mode="json") for question in request.custom_questions]
            if request.custom_questions is not None
            else None
        ),
        custom_details=(
            [detail.model_dump(mode="json") for detail in request.custom_details]
            if request.custom_details is not None
            else None
        ),
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
                "whatsapp_broadcast_group_ids": [str(summary.id) for summary in summaries],
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
    return ClientGroupResponse.model_validate(client_group_output_from_entity(group))


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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    group = await ClientGroupRepository(session).get_by_id(link_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found"
        )
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
    dependencies=[Depends(require_cookie_csrf)],
)
async def permanently_delete_client_group(
    link_id: uuid.UUID,
    retain_records: bool = True,
    current_user: User = Depends(require_recent_mfa),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, int | bool]:
    repo = ClientGroupRepository(session)
    destructive_policy = DestructiveMutationPolicy(session)
    mutation = await destructive_policy.require_group(
        user=current_user,
        group_id=link_id,
        action="client_group_permanent_delete",
    )
    group = mutation.group
    if group.status.value == "deleted":
        if group.deletion_retained_records != retain_records:
            await destructive_policy.block_group(
                mutation,
                user=current_user,
                error=ConflictError(
                    "This group was already deleted with a different retention policy.",
                    code="DESTRUCTIVE_REQUEST_CONFLICT",
                ),
            )
        await AuditLogRepository(session).record(
            action="client_group_permanent_delete_idempotent_replay",
            entity_type="client_group",
            entity_id=str(link_id),
            agency_id=group.agency_id,
            user_id=current_user.id,
            actor_email=current_user.email,
            metadata={
                "retained_records": retain_records,
                "request_fingerprint": mutation.request_fingerprint,
            },
        )
        await session.commit()
        return {
            "deleted": True,
            "retained_records": retain_records,
            "historical_passport_count": group.deleted_passport_count,
            "deleted_passport_submissions": 0,
            "deleted_processing_jobs": 0,
            "deleted_qualifier_selections": 0,
            "deleted_storage_objects": 0,
            "storage_cleanup_deferred": not retain_records,
        }
    if group.status.value != "archived":
        await destructive_policy.block_group(
            mutation,
            user=current_user,
            error=ConflictError(
                "Archive the group before permanent deletion",
                code="GROUP_ARCHIVE_REQUIRED",
            ),
        )

    active_resolution_result = await session.execute(
        select(PassportRosterResolutionModel.id)
        .where(
            PassportRosterResolutionModel.client_group_id == link_id,
            PassportRosterResolutionModel.agency_id == group.agency_id,
            PassportRosterResolutionModel.status == "active",
        )
        .limit(1)
    )
    if active_resolution_result.scalar_one_or_none() is not None:
        await destructive_policy.block_group(
            mutation,
            user=current_user,
            error=ConflictError(
                "Restore all active replacement and rejection decisions "
                "before permanently deleting this group.",
                code="PASSPORT_ROSTER_DECISION_ACTIVE",
            ),
        )

    submission_rows = await session.execute(
        select(
            PassportSubmissionModel.id,
            PassportSubmissionModel.image_s3_key,
            PassportSubmissionModel.thumbnail_s3_key,
            PassportSubmissionModel.passport_back_s3_key,
            PassportSubmissionModel.passport_cover_s3_key,
            PassportSubmissionModel.passport_back_cover_s3_key,
            PassportSubmissionModel.passport_photo_s3_key,
        )
        .where(
            PassportSubmissionModel.group_id == link_id,
            PassportSubmissionModel.agency_id == group.agency_id,
        )
        .with_for_update()
    )
    submissions = list(submission_rows.all())
    submission_ids = [row.id for row in submissions]
    storage_keys = passport_storage_keys(submissions)
    crop_repository = PassportImageCropRepository(session)
    storage_keys.extend(await crop_repository.derived_storage_keys(submission_ids))
    storage_keys.extend(await crop_repository.edit_storage_keys(submission_ids))

    await session.execute(
        delete(ManagerGroupAccessModel).where(ManagerGroupAccessModel.group_id == link_id)
    )
    await session.execute(
        delete(ClientGroupWhatsAppBroadcastLinkModel).where(
            ClientGroupWhatsAppBroadcastLinkModel.client_group_id == link_id
        )
    )
    deleted_storage_objects = 0
    deleted_processing_jobs = 0
    deleted_passport_submissions = 0
    deleted_qualifier_selections = 0
    cleanup_jobs: tuple[StorageCleanupJobModel, ...] = ()
    if not retain_records:
        cleanup_jobs = stage_storage_cleanup_jobs(
            session,
            agency_id=group.agency_id,
            source="passport_submission_delete",
            context_id=f"group:{link_id}",
            storage_keys=storage_keys,
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
        qualifier_result = await session.execute(
            delete(QualifierSelectionModel).where(QualifierSelectionModel.group_id == link_id)
        )
        deleted_qualifier_selections = int(getattr(qualifier_result, "rowcount", 0) or 0)
    await session.execute(
        delete(NotificationModel).where(
            NotificationModel.agency_id == group.agency_id,
            NotificationModel.entity_type == "client_group",
            NotificationModel.entity_id == str(link_id),
        )
    )
    policies = await PlatformPolicyRepository(session).load()
    group.mark_deleted(
        passport_count=len(submissions),
        retain_records=retain_records,
        passport_retention_days=policies.passport_data_retention_days,
    )
    await repo.update(group)
    await AuditLogRepository(session).record(
        action="client_group_deleted_with_retention"
        if retain_records
        else "client_group_deleted_with_data_removal",
        entity_type="client_group",
        entity_id=str(link_id),
        agency_id=group.agency_id,
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
            "storage_objects_scheduled_for_cleanup": len(storage_keys)
            if not retain_records
            else 0,
            "storage_cleanup_job_count": len(cleanup_jobs),
            "request_fingerprint": mutation.request_fingerprint,
            "passport_purge_at": (
                group.passport_purge_at.isoformat()
                if group.passport_purge_at is not None
                else None
            ),
        },
    )
    try:
        await session.commit()
    except Exception as exc:
        await record_destructive_failure(
            mutation,
            user=current_user,
            error=exc,
        )
        raise
    return {
        "deleted": True,
        "retained_records": retain_records,
        "historical_passport_count": len(submissions),
        "deleted_passport_submissions": deleted_passport_submissions,
        "deleted_processing_jobs": deleted_processing_jobs,
        "deleted_qualifier_selections": deleted_qualifier_selections,
        "deleted_storage_objects": deleted_storage_objects,
        "storage_cleanup_deferred": bool(cleanup_jobs),
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
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions"
        )

    group = await ClientGroupRepository(session).get_by_id(link_id)
    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Client group was not found"
        )
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


async def _delete_by_ids(
    session: AsyncSession,
    model: type[PassportProcessingJobModel] | type[PassportSubmissionModel],
    column: InstrumentedAttribute[uuid.UUID],
    ids: list[uuid.UUID],
) -> int:
    if not ids:
        return 0
    result = await session.execute(delete(model).where(column.in_(ids)))
    return int(result.rowcount or 0)
