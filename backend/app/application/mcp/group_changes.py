"""Reviewed group creation through the website's flush-only application use case."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.application.dtos.client_group_dtos import CreateClientGroupInputDTO
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.operations import (
    MCPCreatedEntity,
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.application.use_cases.client_groups.create_client_group_use_case import (
    CreateClientGroupUseCase,
)
from app.domain.entities.entities import UserRole
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.models import AgencyModel, UserModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.platform_policy_repository import PlatformPolicyRepository

CREATE_GROUP_POLICY = MCPToolPolicy(
    "create_group", MCPCapability.CHANGE, frozenset({"create_group"})
)
_OWNER_ROLES = frozenset(
    {
        UserRole.SUPER_ADMIN.value,
        UserRole.AGENCY_ADMIN.value,
        UserRole.AGENCY_MANAGER.value,
        UserRole.AGENCY_STAFF.value,
    }
)


@dataclass(frozen=True, slots=True)
class MCPGroupCreationCommand:
    agency_id: uuid.UUID
    owner_user_id: uuid.UUID
    group: CreateClientGroupInputDTO


def group_creation_operation(
    validate: Callable[[dict[str, Any]], MCPGroupCreationCommand],
) -> MCPDatabaseOperation:
    """Validation is supplied by the typed transport, never by tool arguments.

    The transport uses the existing website creation schema. The same domain
    entity and persisted platform policies still validate the actual creation.
    This adapter creates no broadcasts, members, files, jobs or external sends.
    """

    async def create(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        command = validate(payload)
        session = context.session
        actor = await session.get(UserModel, context.principal.user_id)
        if actor is None or not actor.is_active or actor.deleted_at or actor.role != "super_admin":
            raise MCPAuthError("access_denied", 403)
        agency = await session.scalar(
            select(AgencyModel)
            .where(
                AgencyModel.id == command.agency_id,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if agency is None or not agency.is_active:
            raise MCPOperationError("group_agency_unavailable")
        owner = await session.scalar(
            select(UserModel)
            .where(
                UserModel.id == command.owner_user_id,
            )
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if (
            owner is None
            or not owner.is_active
            or owner.deleted_at is not None
            or owner.agency_id != agency.id
            or owner.role not in _OWNER_ROLES
        ):
            raise MCPOperationError("group_owner_unavailable")
        policies = PlatformPolicyRepository(session)
        if (
            owner.role == UserRole.AGENCY_MANAGER.value
            and not (await policies.load()).allow_manager_group_creation
        ):
            raise MCPOperationError("group_owner_creation_disabled")
        result = await CreateClientGroupUseCase(ClientGroupRepository(session), policies).execute(
            command.group,
            agency_id=agency.id,
            created_by_user_id=owner.id,
        )
        audit = await AuditLogRepository(session).record(
            action="client_group_created",
            entity_type="client_group",
            entity_id=str(result.id),
            agency_id=agency.id,
            user_id=actor.id,
            actor_email=actor.email,
            metadata={
                "import_only": result.import_only,
                "whatsapp_broadcast_count": 0,
                "whatsapp_broadcast_group_ids": [],
                "owner_user_id": str(owner.id),
                "mcp_operation_id": str(context.operation_id),
            },
        )
        # The secure public-upload token intentionally stays in the application.
        # Stable entity references can be replayed without retaining a bearer URL.
        return MCPDatabaseResult(
            {
                "group_id": str(result.id),
                "name": result.name,
                "agency_id": str(agency.id),
                "owner_user_id": str(owner.id),
                "status": result.status,
                "import_only": result.import_only,
                "destination": result.destination,
                "travel_date": result.travel_date.isoformat() if result.travel_date else None,
                "return_date": result.return_date.isoformat() if result.return_date else None,
                "timezone": result.timezone,
                "business_audit_id": str(audit.id),
                "public_collection_enabled": not result.import_only and result.status == "active",
            },
            created_entities=(
                MCPCreatedEntity("client_group", str(result.id), f"/passports/groups/{result.id}"),
            ),
        )

    return MCPDatabaseOperation(CREATE_GROUP_POLICY, create)
