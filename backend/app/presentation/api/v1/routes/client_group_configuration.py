"""Configuration for upload links; HTTP declarations remain in client_groups."""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.companies.access import company_agency_scope
from app.application.companies.assignment import assign_group_company
from app.application.dtos.client_group_dtos import (
    CreateClientGroupInputDTO,
    client_group_output_from_entity,
)
from app.application.security.authorization_policy import AuthorizationPolicy
from app.application.use_cases.client_groups.create_client_group_use_case import (
    CreateClientGroupUseCase,
)
from app.domain.entities.entities import (
    User,
)
from app.domain.exceptions.exceptions import (
    AuthorizationError,
)
from app.infrastructure.database.models import (
    PassengerQRTokenModel,
    PassportSubmissionModel,
)
from app.infrastructure.repositories.audit_log_repository import (
    AuditLogRepository as AuditLogRepositoryType,
)
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.presentation.api.v1.routes.client_group_operation_dependencies import (
    ReplaceWhatsappLinks,
    RequireClientGroupCreationAccess,
    RequireWhatsappBroadcastAccess,
    SyncGroupBroadcastContacts,
    ValidateBroadcastIds,
)
from app.presentation.api.v1.routes.tour_operations_qr_helpers import qr_expires_at_for_group
from app.presentation.api.v1.schemas.client_group_schemas import (
    ClientGroupResponse,
    CreateClientGroupRequest,
    UpdateClientGroupRequest,
)
from app.presentation.api.v1.schemas.company_schemas import CompanyAssignmentRequest


async def create_client_group(
    request: CreateClientGroupRequest,
    current_user: User,
    use_case: CreateClientGroupUseCase,
    session: AsyncSession,
    *,
    _replace_whatsapp_links: ReplaceWhatsappLinks,
    _require_client_group_creation_access: RequireClientGroupCreationAccess,
    _require_whatsapp_broadcast_access: RequireWhatsappBroadcastAccess,
    _validate_broadcast_ids: ValidateBroadcastIds,
    AuditLogRepository: type[AuditLogRepositoryType],
) -> ClientGroupResponse:
    tenant_id = company_agency_scope(current_user, request.agency_id)

    await _require_client_group_creation_access(current_user, session)

    if request.whatsapp_broadcast_group_ids:
        _require_whatsapp_broadcast_access(current_user)

    dto = CreateClientGroupInputDTO(
        name=request.name,
        company_id=request.company_id,
        import_only=request.import_only,
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
        upload_configuration=(
            request.upload_configuration.model_dump(mode="json")
            if request.upload_configuration is not None
            else None
        ),
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
        agency_id=tenant_id,
        broadcast_ids=request.whatsapp_broadcast_group_ids,
    )
    result = await use_case.execute(
        dto=dto,
        agency_id=tenant_id,
        created_by_user_id=current_user.id,
    )
    linked, _, _ = await _replace_whatsapp_links(
        session,
        group_id=result.id,
        agency_id=tenant_id,
        created_by_user_id=current_user.id,
        broadcast_ids=request.whatsapp_broadcast_group_ids,
        matching_fields_by_broadcast=request.matching_fields_by_broadcast,
    )
    await AuditLogRepository(session).record(
        action="client_group_created",
        entity_type="client_group",
        entity_id=str(result.id),
        agency_id=tenant_id,
        user_id=current_user.id,
        actor_email=current_user.email,
        metadata={
            "import_only": result.import_only,
            "whatsapp_broadcast_count": len(linked),
            "whatsapp_broadcast_group_ids": [str(summary.id) for summary in linked],
        },
    )
    return ClientGroupResponse.model_validate(result)


async def assign_client_group_company(
    link_id: uuid.UUID,
    body: CompanyAssignmentRequest,
    agency_id: uuid.UUID | None,
    current_user: User,
    session: AsyncSession,
) -> ClientGroupResponse:
    scope = company_agency_scope(current_user, agency_id)
    model = await assign_group_company(
        session,
        user=current_user,
        agency_id=scope,
        group_id=link_id,
        company_id=body.company_id,
        expected_revision=body.expected_revision,
    )
    entity = ClientGroupRepository._to_entity(model)
    return ClientGroupResponse.model_validate(client_group_output_from_entity(entity))


async def update_client_group(
    link_id: uuid.UUID,
    request: UpdateClientGroupRequest,
    current_user: User,
    session: AsyncSession,
    *,
    _replace_whatsapp_links: ReplaceWhatsappLinks,
    _require_whatsapp_broadcast_access: RequireWhatsappBroadcastAccess,
    sync_group_broadcast_contacts: SyncGroupBroadcastContacts,
    AuditLogRepository: type[AuditLogRepositoryType],
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

    if "company_id" in request.model_fields_set:
        if request.company_id is None:
            raise HTTPException(status_code=422, detail="Company assignment cannot be cleared")
        assigned = await assign_group_company(
            session,
            user=current_user,
            agency_id=company_agency_scope(current_user, request.agency_id),
            group_id=group.id,
            company_id=request.company_id,
            expected_revision=request.company_revision,
        )
        group = repo._to_entity(assigned)

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
        upload_configuration=(
            request.upload_configuration.model_dump(mode="json")
            if request.upload_configuration is not None
            else None
        ),
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
    await sync_group_broadcast_contacts(
        session,
        agency_id=group.agency_id,
        group_id=group.id,
        actor_user_id=current_user.id,
    )
    if request.whatsapp_broadcast_group_ids is not None:
        summaries, previous_ids, changed = await _replace_whatsapp_links(
            session,
            group_id=group.id,
            agency_id=group.agency_id,
            created_by_user_id=current_user.id,
            broadcast_ids=request.whatsapp_broadcast_group_ids,
            matching_fields_by_broadcast=request.matching_fields_by_broadcast,
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
