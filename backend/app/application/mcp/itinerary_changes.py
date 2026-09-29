"""Retained GC itinerary drafts without publication or notification effects."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.application.mcp.change_context import require_change_actor
from app.application.mcp.operations import (
    MCPCreatedEntity,
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.application.use_cases.gc_app.create_itinerary import create_itinerary_version
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.gc_mobile_models import GCItineraryVersionModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


@dataclass(frozen=True, slots=True)
class ItineraryCreationSupport:
    access_context: Callable[..., Any]
    require_publishable_group: Callable[..., Any]
    require_access_revision: Callable[..., Any]
    checksum: Callable[..., str]


@dataclass(frozen=True, slots=True)
class ItineraryCreationCommand:
    agency_id: uuid.UUID
    group_id: uuid.UUID
    body: Any


def itinerary_creation_operation(
    *,
    support: ItineraryCreationSupport,
    validate: Callable[[dict[str, Any]], ItineraryCreationCommand],
) -> MCPDatabaseOperation:
    async def create(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        command = validate(payload)
        actor = await require_change_actor(context, command.agency_id)
        access, group = await support.access_context(
            context.session, actor, command.group_id, agency_id=command.agency_id, lock=True
        )
        support.require_publishable_group(group)
        support.require_access_revision(access, command.body.expected_access_revision)
        if group.deleted_at is not None:
            raise MCPOperationError("itinerary_group_unavailable")
        version = await create_itinerary_version(
            context.session,
            access=access,
            group_id=group.id,
            actor_id=actor.id,
            body=command.body,
            checksum=support.checksum(command.body.model_dump(mode="json", by_alias=True)),
        )
        data = {
            "agency_id": str(command.agency_id),
            "group_id": str(group.id),
            "access_id": str(access.id),
            "itinerary_id": str(version.id),
            "version": version.version,
            "access_revision": access.revision,
            "status": "draft",
            "notifications_queued": 0,
            "day_count": len(command.body.days),
            "item_count": sum(len(day.items) for day in command.body.days),
        }
        audit = await AuditLogRepository(context.session).record(
            action="gc_app.itinerary_draft_created",
            entity_type="gc_itinerary_version",
            entity_id=str(version.id),
            agency_id=command.agency_id,
            user_id=actor.id,
            actor_email=actor.email,
            metadata={**data, "mcp_operation_id": str(context.operation_id)},
        )
        data["business_audit_id"] = str(audit.id)
        return MCPDatabaseResult(
            data,
            created_entities=(
                MCPCreatedEntity("gc_itinerary_version", str(version.id), "/gc-app"),
            ),
        )

    async def authorize_receipt(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        data = receipt["data"]
        agency_id, group_id = uuid.UUID(data["agency_id"]), uuid.UUID(data["group_id"])
        actor = await require_change_actor(context, agency_id)
        access, group = await support.access_context(
            context.session, actor, group_id, agency_id=agency_id, lock=True
        )
        support.require_publishable_group(group)
        if group.deleted_at is not None or str(access.id) != data["access_id"]:
            raise MCPOperationError("itinerary_receipt_unavailable")
        found = await context.session.scalar(
            select(GCItineraryVersionModel.id).where(
                GCItineraryVersionModel.id == uuid.UUID(data["itinerary_id"]),
                GCItineraryVersionModel.agency_id == agency_id,
                GCItineraryVersionModel.group_id == group_id,
                GCItineraryVersionModel.gc_group_access_id == access.id,
            )
        )
        if found is None:
            raise MCPOperationError("itinerary_receipt_unavailable")

    return MCPDatabaseOperation(
        MCPToolPolicy(
            "create_gc_itinerary_draft",
            MCPCapability.CHANGE,
            frozenset({"create_itinerary_version"}),
        ),
        create,
        authorize_receipt,
    )
