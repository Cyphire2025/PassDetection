"""Prepare and confirm exact document sends with durable, original authority."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError, utc
from app.application.mcp.operations import (
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.application.mcp.permissions import require_tool_access
from app.application.mcp.whatsapp_intents import snapshot_hash
from app.application.security.authorization_policy import AuthorizationPolicy
from app.core.config.settings import Settings
from app.domain.exceptions.exceptions import AuthorizationError
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.mcp_document_delivery_models import (
    MCPDocumentDeliveryOutboxModel,
    MCPDocumentDeliveryPlanModel,
)
from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    DocumentDistributionBatchModel,
)
from app.infrastructure.repositories.user_repository import UserRepository

CONFIRM_TOOL = "confirm_whatsapp_document_delivery"
Snapshot = Callable[..., Awaitable[tuple[dict[str, Any], Any]]]


async def authorized_document_plan(
    context: MCPDatabaseContext, identifier: uuid.UUID, settings: Settings, *, lock: bool = True,
) -> MCPDocumentDeliveryPlanModel:
    identity = await context.session.scalar(select(MCPDocumentDeliveryPlanModel).where(
        MCPDocumentDeliveryPlanModel.id == identifier,
        MCPDocumentDeliveryPlanModel.user_id == context.principal.user_id,
    ))
    if identity is None:
        raise MCPAuthError("access_denied", 403)
    # The current connection's operation barrier is already held. Original
    # authority is acquired before plan/business locks, including receipt replay.
    grant = await MCPAuthorizationService(context.session, settings).require_grant(
        identity.original_grant_id, lock=True,
    )
    await require_tool_access(context.session, settings, grant.id, CONFIRM_TOOL, "mcp:communicate", lock=False)
    if grant.user_id != context.principal.user_id:
        raise MCPAuthError("access_denied", 403)
    statement = select(MCPDocumentDeliveryPlanModel).where(
        MCPDocumentDeliveryPlanModel.id == identifier,
        MCPDocumentDeliveryPlanModel.user_id == grant.user_id,
        MCPDocumentDeliveryPlanModel.original_grant_id == grant.id,
    ).execution_options(populate_existing=True)
    if lock:
        statement = statement.with_for_update()
    plan = await context.session.scalar(statement)
    if plan is None:
        raise MCPAuthError("access_denied", 403)
    user = await UserRepository(context.session).get_by_id(grant.user_id)
    if user is None:
        raise MCPAuthError("access_denied", 403)
    group = await context.session.scalar(select(ClientGroupModel).join(AgencyModel).where(
        ClientGroupModel.id == plan.group_id, ClientGroupModel.agency_id == plan.agency_id,
        ClientGroupModel.deleted_at.is_(None), ClientGroupModel.status.not_in(("archived", "deleted")),
        AgencyModel.is_active.is_(True),
    ).execution_options(populate_existing=True))
    batch = await context.session.scalar(select(DocumentDistributionBatchModel.id).where(
        DocumentDistributionBatchModel.id == plan.document_batch_id,
        DocumentDistributionBatchModel.agency_id == plan.agency_id,
        DocumentDistributionBatchModel.group_id == plan.group_id,
    ))
    if group is None or batch is None:
        raise MCPAuthError("access_denied", 403)
    try:
        await AuthorizationPolicy(context.session).require_export_data(user, group)
    except AuthorizationError as exc:
        raise MCPAuthError("access_denied", 403) from exc
    return plan


def document_delivery_operations(settings: Settings, snapshot_callback: Snapshot) -> tuple[MCPDatabaseOperation, ...]:
    async def authorize_receipt(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        await authorized_document_plan(context, uuid.UUID(receipt["data"]["plan_id"]), settings, lock=False)

    async def prepare(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        snapshot, _ = await snapshot_callback(context, payload, settings)
        now = datetime.now(UTC)
        plan = MCPDocumentDeliveryPlanModel(
            id=uuid.uuid4(), operation_id=context.operation_id,
            user_id=context.principal.user_id, original_grant_id=context.principal.grant_id,
            agency_id=uuid.UUID(snapshot["agency_id"]), group_id=uuid.UUID(snapshot["group_id"]),
            document_batch_id=uuid.UUID(snapshot["document_batch_id"]), snapshot=snapshot,
            snapshot_hash=snapshot_hash(snapshot), status="prepared", prepared_at=now,
            expires_at=now + timedelta(minutes=15),
        )
        context.session.add(plan)
        await context.session.flush()
        return MCPDatabaseResult({
            "plan_id": str(plan.id), "plan_hash": plan.snapshot_hash,
            "expires_at": plan.expires_at.isoformat(), "status": "prepared", "preview": snapshot,
            "confirmation_required": True,
            "notice": "Prepared only. Present the exact message, chosen attachments, recipients and exclusions, then ask for final approval. No message is queued or sent.",
        })

    async def confirm(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        if set(payload) != {"plan_id", "plan_hash", "user_confirmed"} or payload.get("user_confirmed") is not True:
            raise MCPOperationError("invalid_document_delivery_confirmation")
        plan = await authorized_document_plan(context, uuid.UUID(payload["plan_id"]), settings)
        if payload["plan_hash"] != plan.snapshot_hash:
            raise MCPOperationError("document_delivery_hash_mismatch")
        if plan.status in {"queued", "completed"}:
            return MCPDatabaseResult({"plan_id": str(plan.id), "send_batch_id": str(plan.send_batch_id),
                                      "plan_hash": plan.snapshot_hash, "status": "queued"},
                                     status="queued", workflow_id=plan.send_batch_id)
        if plan.status != "prepared" or utc(plan.expires_at) <= datetime.now(UTC):
            raise MCPOperationError("document_delivery_plan_expired_or_closed")
        _, response = await snapshot_callback(context, plan.snapshot["request"], settings,
                                                       expected_hash=plan.snapshot_hash)
        now = datetime.now(UTC)
        plan.status, plan.confirmed_at, plan.send_batch_id = "queued", now, response.send_batch_id
        context.session.add(MCPDocumentDeliveryOutboxModel(
            id=uuid.uuid4(), plan_id=plan.id, send_batch_id=response.send_batch_id,
            status="pending", publication_attempts=0, next_attempt_at=now, created_at=now, updated_at=now,
        ))
        await context.session.flush()
        return MCPDatabaseResult({"plan_id": str(plan.id), "send_batch_id": str(plan.send_batch_id),
                                  "plan_hash": plan.snapshot_hash, "status": "queued"},
                                 status="queued", workflow_id=plan.send_batch_id)

    return tuple(MCPDatabaseOperation(
        MCPToolPolicy(name, MCPCapability.COMMUNICATE, frozenset({effect})), callback, authorize_receipt,
    ) for name, effect, callback in (
        ("prepare_whatsapp_document_delivery", "prepare_communication", prepare),
        (CONFIRM_TOOL, "queue_communication", confirm),
    ))
