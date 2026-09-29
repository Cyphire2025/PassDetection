"""Retained GC announcement versions, never publication or source-row deletion."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from app.application.mcp.change_context import require_change_actor
from app.application.mcp.operations import (
    MCPCreatedEntity,
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.application.use_cases.gc_app.create_announcement import (
    AnnouncementContent,
    create_announcement_version,
)
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.gc_mobile_models import GCAnnouncementModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository


@dataclass(frozen=True, slots=True)
class AnnouncementSupport:
    access_context: Callable[..., Any]
    require_publishable_group: Callable[..., Any]
    require_access_revision: Callable[..., Any]
    validate_window: Callable[..., Any]


@dataclass(frozen=True, slots=True)
class AnnouncementCommand:
    agency_id: uuid.UUID
    group_id: uuid.UUID
    expected_access_revision: int
    content: AnnouncementContent
    previous_id: uuid.UUID | None = None


def announcement_operation(
    *,
    revision: bool,
    support: AnnouncementSupport,
    validate: Callable[[dict[str, Any]], AnnouncementCommand],
) -> MCPDatabaseOperation:
    async def create(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        command = validate(payload)
        actor = await require_change_actor(context, command.agency_id)
        access, group = await support.access_context(
            context.session, actor, command.group_id, agency_id=command.agency_id, lock=True
        )
        support.require_publishable_group(group)
        support.require_access_revision(access, command.expected_access_revision)
        support.validate_window(command.content.available_from, command.content.available_until)
        if group.deleted_at is not None:
            raise MCPOperationError("announcement_unavailable")
        logical_id, version = uuid.uuid4(), 1
        if revision:
            previous = await context.session.scalar(
                select(GCAnnouncementModel)
                .where(
                    GCAnnouncementModel.id == command.previous_id,
                    GCAnnouncementModel.agency_id == command.agency_id,
                    GCAnnouncementModel.group_id == command.group_id,
                    GCAnnouncementModel.gc_group_access_id == access.id,
                )
                .with_for_update()
            )
            if previous is None:
                raise MCPOperationError("announcement_unavailable")
            logical_id = previous.logical_announcement_id
            version = 1 + int(
                await context.session.scalar(
                    select(func.max(GCAnnouncementModel.version)).where(
                        GCAnnouncementModel.gc_group_access_id == access.id,
                        GCAnnouncementModel.logical_announcement_id == logical_id,
                    )
                )
                or 0
            )
        row = await create_announcement_version(
            context.session,
            access=access,
            actor_id=actor.id,
            content=command.content,
            logical_id=logical_id,
            version=version,
        )
        data = {
            "agency_id": str(command.agency_id),
            "group_id": str(command.group_id),
            "access_id": str(access.id),
            "announcement_id": str(row.id),
            "logical_announcement_id": str(row.logical_announcement_id),
            "previous_announcement_id": str(command.previous_id) if command.previous_id else None,
            "version": row.version,
            "access_revision": access.revision,
            "status": "draft",
            "notifications_queued": 0,
            "previous_versions_preserved": True,
        }
        audit = await AuditLogRepository(context.session).record(
            action="gc_app.announcement_draft_created",
            entity_type="gc_announcement",
            entity_id=str(row.id),
            agency_id=command.agency_id,
            user_id=actor.id,
            actor_email=actor.email,
            metadata={**data, "mcp_operation_id": str(context.operation_id)},
        )
        data["business_audit_id"] = str(audit.id)
        return MCPDatabaseResult(
            data, created_entities=(MCPCreatedEntity("gc_announcement", str(row.id), "/gc-app"),)
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
            raise MCPOperationError("announcement_unavailable")
        retained = await context.session.scalar(
            select(GCAnnouncementModel.id).where(
                GCAnnouncementModel.id == uuid.UUID(data["announcement_id"]),
                GCAnnouncementModel.agency_id == agency_id,
                GCAnnouncementModel.group_id == group_id,
                GCAnnouncementModel.gc_group_access_id == access.id,
            )
        )
        if retained is None:
            raise MCPOperationError("announcement_unavailable")

    return MCPDatabaseOperation(
        MCPToolPolicy(
            "create_gc_announcement_revision" if revision else "create_gc_announcement_draft",
            MCPCapability.CHANGE,
            frozenset({"create_announcement_version"}),
        ),
        create,
        authorize_receipt,
    )
