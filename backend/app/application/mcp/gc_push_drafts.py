"""Append-only authored draft creation; no notification, device or provider effects."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import Field
from sqlalchemy import select

from app.application.dtos.gc_notifications import NotificationDraftInput
from app.application.mcp.credentials import MCPAuthError
from app.application.mcp.gc_push_snapshots import active_agency
from app.application.mcp.operations import (
    MCPCreatedEntity,
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.application.mobile.authored_notification_service import save_notification_draft
from app.application.mobile.notification_errors import NotificationWorkflowError
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.gc_notification_models import GCNotificationDraftModel


class GCPushDraftCreation(NotificationDraftInput):
    agency_id: uuid.UUID
    audience: Literal["selected_groups"] = "selected_groups"
    group_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)


def gc_push_draft_operation() -> MCPDatabaseOperation:
    async def authorize_receipt(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        agency_id = uuid.UUID(receipt["data"]["agency_id"])
        await active_agency(context.session, agency_id)
        draft = await context.session.scalar(
            select(GCNotificationDraftModel).where(
                GCNotificationDraftModel.id == uuid.UUID(receipt["data"]["draft_id"]),
                GCNotificationDraftModel.agency_id == agency_id,
                GCNotificationDraftModel.deleted_at.is_(None),
            )
        )
        if draft is None:
            raise MCPAuthError("access_denied", 403)

    async def create(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        request = GCPushDraftCreation.model_validate(payload)
        await active_agency(context.session, request.agency_id)
        try:
            draft = await save_notification_draft(
                context.session,
                agency_id=request.agency_id,
                actor_id=context.principal.user_id,
                body=NotificationDraftInput.model_validate(
                    request.model_dump(exclude={"agency_id"})
                ),
            )
        except NotificationWorkflowError as exc:
            raise MCPOperationError("gc_push_audience_unavailable") from exc
        return MCPDatabaseResult(
            {
                "agency_id": str(draft.agency_id),
                "draft_id": str(draft.id),
                "revision": draft.revision,
                "status": draft.status,
                "title": draft.title,
                "body": draft.body,
                "group_ids": draft.group_ids,
                "group_names": draft.group_names,
                "content_trust": "untrusted_business_data",
                "messages_queued": 0,
                "notice": "New draft saved. Prepare and review its exact audience and content before confirmation.",
            },
            created_entities=(
                MCPCreatedEntity("gc_notification_draft", str(draft.id), "/gc-app/notifications"),
            ),
        )

    return MCPDatabaseOperation(
        MCPToolPolicy("create_gc_push_draft", MCPCapability.CHANGE, frozenset({"create"})),
        create,
        authorize_receipt,
    )
