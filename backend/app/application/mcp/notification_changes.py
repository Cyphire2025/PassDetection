"""Durable, personally targeted first-read acknowledgement with no send effects."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.application.mcp.credentials import utc
from app.application.mcp.operations import (
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.application.mcp.read_context import MCPReadContext
from app.application.use_cases.notifications.scope import direct_notification_agency
from app.domain.exceptions.exceptions import EntityNotFoundError
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.models import NotificationModel
from app.infrastructure.repositories.audit_log_repository import AuditLogRepository
from app.infrastructure.repositories.notification_feed_queries import direct_predicates
from app.infrastructure.repositories.notification_repository import NotificationRepository


def _busy(error: DBAPIError) -> bool:
    return getattr(error.orig, "sqlstate", getattr(error.orig, "pgcode", None)) == "55P03"


def notification_acknowledgement_operation(cursor_secret: str) -> MCPDatabaseOperation:
    policy = MCPToolPolicy("acknowledge_my_notification", MCPCapability.CHANGE,
                           frozenset({"acknowledge_personal_notification"}))

    async def scope(context: MCPDatabaseContext) -> UUID | None:
        actor = await MCPReadContext(context.session, cursor_secret=cursor_secret,
                                     namespace="personal-notifications")._actor(context.principal.user_id, 1)
        return direct_notification_agency(actor)

    async def acknowledge(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        try:
            if set(payload) != {"notification_id"} or type(payload["notification_id"]) is not str:
                raise ValueError
            identifier = UUID(payload["notification_id"])
        except (ValueError, TypeError, KeyError) as exc:
            raise MCPOperationError("invalid_notification_acknowledgement") from exc
        agency_scope = await scope(context)
        try:
            agency_id, read_at, changed = await NotificationRepository(context.session).acknowledge_direct_read(
                notification_id=identifier, user_id=context.principal.user_id, agency_id=agency_scope)
        except EntityNotFoundError as exc:
            raise MCPOperationError("notification_unavailable") from exc
        except DBAPIError as exc:
            if _busy(exc):
                raise MCPOperationError("notification_busy") from exc
            raise
        data = {"notification_id": str(identifier), "agency_id": str(agency_id), "is_read": True,
                "read_at": utc(read_at).isoformat() if read_at else None, "changed": changed,
                "messages_queued": 0, "notification_created": False}
        audit = await AuditLogRepository(context.session).record(
            action="notification.mcp_acknowledged", entity_type="notification", entity_id=str(identifier),
            user_id=context.principal.user_id, agency_id=agency_id,
            metadata={"mcp_operation_id": str(context.operation_id), "changed": changed})
        data["business_audit_id"] = str(audit.id)
        return MCPDatabaseResult(data)

    async def authorize_receipt(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        agency_scope = await scope(context)
        data = receipt["data"]
        try:
            row = await context.session.scalar(select(NotificationModel.id).where(
                NotificationModel.id == UUID(data["notification_id"]),
                NotificationModel.agency_id == UUID(data["agency_id"]),
                *direct_predicates(context.principal.user_id, agency_scope),
                NotificationModel.is_read.is_(True),
            ).with_for_update(read=True, nowait=True))
        except DBAPIError as exc:
            if _busy(exc):
                raise MCPOperationError("notification_busy") from exc
            raise
        if row is None:
            raise MCPOperationError("notification_unavailable")

    return MCPDatabaseOperation(policy, acknowledge, authorize_receipt)
