"""
Upload Links Routes — /api/v1/upload-links
==========================================
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    Header,
    Query,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.application.mobile.passenger_change_propagation import (
    reconcile_mobile_passenger_access_for_group,
)
from app.application.security.destructive_mutation_policy import (
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
from app.application.use_cases.whatsapp.group_submission_matching import (
    SubmissionMatchRow,
)
from app.domain.entities.entities import (
    ClientGroup,
    User,
)
from app.infrastructure.database.models import (
    PassportProcessingJobModel,
    PassportRosterResolutionModel,
    PassportSubmissionModel,
    WhatsAppBroadcastRecipientModel,
)
from app.infrastructure.database.session import get_db_session
from app.infrastructure.documents.storage_cleanup import stage_storage_cleanup_jobs
from app.infrastructure.observability.operational_events import record_operational_event
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.passport_roster_resolution_repository import (
    lock_linked_whatsapp_broadcast_groups,
    lock_whatsapp_broadcast_groups,
    suppress_active_replacement_recipients,
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
from app.infrastructure.whatsapp.private_delivery_policy import (
    prepare_private_delivery_identity_mutation,
)
from app.infrastructure.whatsapp.source_group_sync import sync_group_broadcast_contacts
from app.presentation.api.v1.pagination import PageOffset, PageSize
from app.presentation.api.v1.routes import client_group_access as _client_group_access
from app.presentation.api.v1.routes import (
    client_group_broadcast_links as _client_group_broadcast_links,
)
from app.presentation.api.v1.routes import client_group_configuration as _client_group_configuration
from app.presentation.api.v1.routes import (
    client_group_link_operations as _client_group_link_operations,
)
from app.presentation.api.v1.routes import client_group_match_queries as _client_group_match_queries
from app.presentation.api.v1.routes import (
    client_group_permanent_delete as _client_group_permanent_delete,
)
from app.presentation.api.v1.routes import (
    client_group_public_collection as _client_group_public_collection,
)
from app.presentation.api.v1.routes import client_group_reads as _client_group_reads
from app.presentation.api.v1.routes import (
    client_group_rejection_resolution as _client_group_rejection_resolution,
)
from app.presentation.api.v1.routes import (
    client_group_replacement_resolution as _client_group_replacement_resolution,
)
from app.presentation.api.v1.routes import (
    client_group_resolution_restore as _client_group_resolution_restore,
)
from app.presentation.api.v1.routes import client_group_retention as _client_group_retention
from app.presentation.api.v1.routes import (
    client_group_whatsapp_match_support as _whatsapp_match_support,
)
from app.presentation.api.v1.routes.client_group_broadcast_configuration import (
    _broadcast_summaries as _broadcast_summaries,
)
from app.presentation.api.v1.routes.client_group_broadcast_configuration import (
    _linked_broadcast_summaries_by_group as _linked_broadcast_summaries_by_group,
)
from app.presentation.api.v1.routes.client_group_broadcast_configuration import (
    requested_link_configuration as requested_link_configuration,
)
from app.presentation.api.v1.routes.client_group_broadcast_configuration import (
    summaries_with_matching_fields as summaries_with_matching_fields,
)
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
    ReplaceWhatsAppBroadcastLinksRequest,
    ResolveUnidentifiedReplacementRequest,
    UpdateClientGroupRequest,
    WhatsAppBroadcastSummaryResponse,
)
from app.presentation.api.v1.schemas.company_schemas import CompanyAssignmentRequest
from app.presentation.dependencies.auth import (
    get_current_active_user,
    require_recent_mfa,
)
from app.presentation.dependencies.csrf import require_cookie_csrf

router = APIRouter()


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
    return _client_group_access._owner_scope_for(user)


def _require_whatsapp_broadcast_access(user: User) -> None:
    return _client_group_access._require_whatsapp_broadcast_access(user)


async def _validate_broadcast_ids(
    session: AsyncSession,
    *,
    agency_id: uuid.UUID,
    broadcast_ids: list[uuid.UUID],
    allowed_archived_ids: list[uuid.UUID] | None = None,
) -> list[WhatsAppBroadcastSummaryResponse]:
    return await _client_group_broadcast_links._validate_broadcast_ids(
        session,
        agency_id=agency_id,
        broadcast_ids=broadcast_ids,
        allowed_archived_ids=allowed_archived_ids,
    )


async def _replace_whatsapp_links(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
    created_by_user_id: uuid.UUID,
    broadcast_ids: list[uuid.UUID],
    matching_fields_by_broadcast: dict[uuid.UUID, list[str]] | None = None,
) -> tuple[list[WhatsAppBroadcastSummaryResponse], list[uuid.UUID], bool]:
    # Serialize link-set edits for this passport group. Broadcast rows are then
    # locked in the same stable order used by replacement creation so an
    # unlink cannot pass the active-replacement check concurrently.
    return await _client_group_broadcast_links._replace_whatsapp_links(
        session,
        group_id=group_id,
        agency_id=agency_id,
        created_by_user_id=created_by_user_id,
        broadcast_ids=broadcast_ids,
        matching_fields_by_broadcast=matching_fields_by_broadcast,
        _validate_broadcast_ids=_validate_broadcast_ids,
        lock_whatsapp_broadcast_groups=lock_whatsapp_broadcast_groups,
        prepare_private_delivery_identity_mutation=prepare_private_delivery_identity_mutation,
        reconcile_mobile_passenger_access_for_group=reconcile_mobile_passenger_access_for_group,
        suppress_active_replacement_recipients=suppress_active_replacement_recipients,
        sync_group_broadcast_contacts=sync_group_broadcast_contacts,
    )


async def _require_client_group_creation_access(
    user: User,
    session: AsyncSession,
) -> None:
    """Apply the server-authoritative role and manager feature policy."""
    return await _client_group_access._require_client_group_creation_access(user, session)


async def _require_managed_group(
    session: AsyncSession,
    current_user: User,
    link_id: uuid.UUID,
    *,
    lock: bool = False,
) -> ClientGroup:
    return await _client_group_access._require_managed_group(
        session, current_user, link_id, lock=lock
    )


async def _require_viewable_group(
    session: AsyncSession,
    current_user: User,
    link_id: uuid.UUID,
) -> ClientGroup:
    return await _client_group_access._require_viewable_group(session, current_user, link_id)


async def _unique_linked_recipient_count(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
) -> int:
    return await _client_group_broadcast_links._unique_linked_recipient_count(
        session, group_id=group_id, agency_id=agency_id
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
    return _client_group_replacement_resolution._require_matching_roster_resolution_replay(
        resolution,
        client_group_id=client_group_id,
        submission_id=submission_id,
        resolution_type=resolution_type,
        broadcast_recipient_id=broadcast_recipient_id,
        conflict_detail=conflict_detail,
    )


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
    return await _client_group_configuration.create_client_group(
        request,
        current_user,
        use_case,
        session,
        _replace_whatsapp_links=_replace_whatsapp_links,
        _require_client_group_creation_access=_require_client_group_creation_access,
        _require_whatsapp_broadcast_access=_require_whatsapp_broadcast_access,
        _validate_broadcast_ids=_validate_broadcast_ids,
        AuditLogRepository=AuditLogRepository,
    )


async def _linked_broadcast_names_for_group(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
) -> dict[uuid.UUID, str]:
    return await _client_group_match_queries._linked_broadcast_names_for_group(
        session, group_id=group_id, agency_id=agency_id
    )


async def _linked_broadcast_matching_fields_for_group(
    session: AsyncSession,
    *,
    group_id: uuid.UUID,
    agency_id: uuid.UUID,
) -> dict[uuid.UUID, tuple[str, ...] | None]:
    return await _client_group_match_queries._linked_broadcast_matching_fields_for_group(
        session, group_id=group_id, agency_id=agency_id
    )


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
    return await _client_group_match_queries._current_unresolved_match_context(
        session, group_id=group_id, agency_id=agency_id
    )


@router.get(
    "",
    response_model=list[ClientGroupResponse],
    status_code=status.HTTP_200_OK,
    summary="List upload links for the current user's agency",
)
async def list_client_groups(
    skip: PageOffset = 0,
    limit: PageSize = 50,
    status_filter: str | None = None,
    current_user: User = Depends(get_current_active_user),
    use_case: ListClientGroupsUseCase = Depends(_get_list_use_case),
) -> list[ClientGroupResponse]:
    return await _client_group_reads.list_client_groups(
        skip, limit, status_filter, current_user, use_case, _owner_scope_for=_owner_scope_for
    )


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
    return await _client_group_reads.list_whatsapp_broadcast_options_for_create(
        current_user, session, _require_whatsapp_broadcast_access=_require_whatsapp_broadcast_access
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
    return await _client_group_reads.list_whatsapp_broadcast_options_for_group(
        link_id,
        current_user,
        session,
        _require_managed_group=_require_managed_group,
        _require_whatsapp_broadcast_access=_require_whatsapp_broadcast_access,
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
    return await _client_group_public_collection.get_client_group_by_token(token, use_case)


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
    return await _client_group_public_collection.record_public_flow_telemetry(
        token, body, upload_session_id, use_case, record_operational_event=record_operational_event
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
    return await _client_group_public_collection.create_qualifier_selection(
        token, request, use_case
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
    return await _client_group_public_collection.get_qualifier_selection(
        token, qualifier_selection_token, use_case
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
    return await _client_group_reads.get_client_group_whatsapp_links(
        link_id,
        current_user,
        session,
        _require_viewable_group=_require_viewable_group,
        _require_whatsapp_broadcast_access=_require_whatsapp_broadcast_access,
        _unique_linked_recipient_count=_unique_linked_recipient_count,
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
    return await _client_group_link_operations.replace_client_group_whatsapp_links(
        link_id,
        body,
        current_user,
        _csrf,
        session,
        _replace_whatsapp_links=_replace_whatsapp_links,
        _require_managed_group=_require_managed_group,
        _require_whatsapp_broadcast_access=_require_whatsapp_broadcast_access,
        _unique_linked_recipient_count=_unique_linked_recipient_count,
        AuditLogRepository=AuditLogRepository,
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
    return await _client_group_link_operations.get_client_group_whatsapp_matches(
        link_id,
        broadcast_id,
        match_status,
        sort_by,
        sort_order,
        page,
        page_size,
        current_user,
        session,
        _linked_broadcast_matching_fields_for_group=_linked_broadcast_matching_fields_for_group,
        _linked_broadcast_names_for_group=_linked_broadcast_names_for_group,
        _require_viewable_group=_require_viewable_group,
        _require_whatsapp_broadcast_access=_require_whatsapp_broadcast_access,
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
    return await _client_group_link_operations.list_replacement_candidates(
        link_id,
        current_user,
        session,
        _linked_broadcast_names_for_group=_linked_broadcast_names_for_group,
        _require_managed_group=_require_managed_group,
        _require_whatsapp_broadcast_access=_require_whatsapp_broadcast_access,
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
    return await _client_group_replacement_resolution.resolve_unidentified_as_replacement(
        link_id,
        submission_id,
        body,
        current_user,
        session,
        _csrf,
        _current_unresolved_match_context=_current_unresolved_match_context,
        _require_managed_group=_require_managed_group,
        _require_matching_roster_resolution_replay=_require_matching_roster_resolution_replay,
        _require_whatsapp_broadcast_access=_require_whatsapp_broadcast_access,
        lock_whatsapp_broadcast_groups=lock_whatsapp_broadcast_groups,
        reconcile_mobile_passenger_access_for_group=reconcile_mobile_passenger_access_for_group,
        suppress_active_replacement_recipients=suppress_active_replacement_recipients,
        sync_group_broadcast_contacts=sync_group_broadcast_contacts,
        AuditLogRepository=AuditLogRepository,
    )


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
    return await _client_group_rejection_resolution.reject_unidentified_upload(
        link_id,
        submission_id,
        body,
        current_user,
        session,
        _csrf,
        _current_unresolved_match_context=_current_unresolved_match_context,
        _require_managed_group=_require_managed_group,
        _require_matching_roster_resolution_replay=_require_matching_roster_resolution_replay,
        _require_whatsapp_broadcast_access=_require_whatsapp_broadcast_access,
        reconcile_mobile_passenger_access_for_group=reconcile_mobile_passenger_access_for_group,
        sync_group_broadcast_contacts=sync_group_broadcast_contacts,
        AuditLogRepository=AuditLogRepository,
    )


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
    return await _client_group_resolution_restore.restore_roster_resolution(
        link_id,
        resolution_id,
        current_user,
        session,
        _csrf,
        _require_managed_group=_require_managed_group,
        _require_whatsapp_broadcast_access=_require_whatsapp_broadcast_access,
        lock_whatsapp_broadcast_groups=lock_whatsapp_broadcast_groups,
        reconcile_mobile_passenger_access_for_group=reconcile_mobile_passenger_access_for_group,
        require_locked_broadcast_recipient_capacity=require_locked_broadcast_recipient_capacity,
        suppress_active_replacement_recipients=suppress_active_replacement_recipients,
        sync_group_broadcast_contacts=sync_group_broadcast_contacts,
        AuditLogRepository=AuditLogRepository,
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
    return await _client_group_retention.revoke_client_group(
        link_id, current_user, use_case, session
    )


@router.patch(
    "/{link_id}/company",
    response_model=ClientGroupResponse,
    dependencies=[Depends(require_cookie_csrf)],
)
async def assign_client_group_company(
    link_id: uuid.UUID,
    body: CompanyAssignmentRequest,
    agency_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db_session),
) -> ClientGroupResponse:
    return await _client_group_configuration.assign_client_group_company(
        link_id, body, agency_id, current_user, session
    )


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
    return await _client_group_configuration.update_client_group(
        link_id,
        request,
        current_user,
        session,
        _replace_whatsapp_links=_replace_whatsapp_links,
        _require_whatsapp_broadcast_access=_require_whatsapp_broadcast_access,
        sync_group_broadcast_contacts=sync_group_broadcast_contacts,
        AuditLogRepository=AuditLogRepository,
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
    return await _client_group_retention.delete_client_group(
        link_id, current_user, use_case, session
    )


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
    return await _client_group_permanent_delete.permanently_delete_client_group(
        link_id,
        retain_records,
        current_user,
        session,
        lock_linked_whatsapp_broadcast_groups=lock_linked_whatsapp_broadcast_groups,
        prepare_private_delivery_identity_mutation=prepare_private_delivery_identity_mutation,
        record_destructive_failure=record_destructive_failure,
        stage_storage_cleanup_jobs=stage_storage_cleanup_jobs,
        sync_group_broadcast_contacts=sync_group_broadcast_contacts,
        AuditLogRepository=AuditLogRepository,
    )


@router.post(
    "/{link_id}/restore",
    response_model=ClientGroupResponse,
    status_code=status.HTTP_200_OK,
    summary="Reopen a closed link or restore an archived or retained deleted client group",
)
async def restore_client_group(
    link_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    use_case: RestoreClientGroupUseCase = Depends(_get_restore_use_case),
    session: AsyncSession = Depends(get_db_session),
) -> ClientGroupResponse:
    return await _client_group_retention.restore_client_group(
        link_id,
        current_user,
        use_case,
        session,
        sync_group_broadcast_contacts=sync_group_broadcast_contacts,
    )


async def _delete_by_ids(
    session: AsyncSession,
    model: type[PassportProcessingJobModel] | type[PassportSubmissionModel],
    column: InstrumentedAttribute[uuid.UUID],
    ids: list[uuid.UUID],
) -> int:
    return await _client_group_permanent_delete._delete_by_ids(session, model, column, ids)
