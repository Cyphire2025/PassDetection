"""Exact reviewed WhatsApp reminder plans; provider work is outside database operations."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

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
from app.application.mcp.whatsapp_media_access import MCPWhatsAppMediaAccess
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.mcp_communication_models import (
    MCPWhatsAppOutboxModel,
    MCPWhatsAppPlanModel,
)
from app.infrastructure.whatsapp.mcp_progress import refresh_mcp_dispatch_progress
from app.infrastructure.whatsapp.publication import fail_unclaimed_broadcast_rows

PrepareSnapshot = Callable[[MCPDatabaseContext, dict[str, Any], bool], Awaitable[dict[str, Any]]]
PLAN_LIFETIME = timedelta(minutes=15)
MAX_PREPARED_RECIPIENTS = 100


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def public_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(snapshot)
    if "header_media" in result:
        result["header_media"].pop("provider_media_id", None)
        result["worker_payload"].pop("header_image_id", None)
        for recipient in result["recipients"]:
            recipient["header_parameters"] = [result["header_media"]["media_handle"]]
    return result


async def owned_plan(
    context: MCPDatabaseContext, plan_id: uuid.UUID, *, lock: bool
) -> MCPWhatsAppPlanModel:
    statement = select(MCPWhatsAppPlanModel).where(
        MCPWhatsAppPlanModel.id == plan_id,
        MCPWhatsAppPlanModel.user_id == context.principal.user_id,
    )
    if lock:
        statement = statement.with_for_update()
    plan = await context.session.scalar(statement.execution_options(populate_existing=True))
    if plan is None or plan.original_grant_id is None:
        raise MCPAuthError("access_denied", 403)
    return plan


def whatsapp_intent_operations(
    prepare_snapshot: PrepareSnapshot,
    settings: Settings,
    *,
    family: Literal["reminder", "message"] = "reminder",
    confirm_snapshot: PrepareSnapshot | None = None,
) -> tuple[MCPDatabaseOperation, ...]:
    async def authorize_receipt(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        plan = await owned_plan(context, uuid.UUID(receipt["data"]["plan_id"]), lock=False)
        if family == "message":
            media_access = MCPWhatsAppMediaAccess(context.session, settings)
            await media_access.authority(context.principal)
            await media_access.scope(plan.agency_id, plan.broadcast_id)

    async def prepare(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        snapshot = await prepare_snapshot(context, payload, True)
        if not 1 <= len(snapshot["recipients"]) <= MAX_PREPARED_RECIPIENTS:
            raise MCPOperationError("whatsapp_plan_audience_unavailable")
        now = datetime.now(UTC)
        plan = MCPWhatsAppPlanModel(
            id=uuid.uuid4(),
            operation_id=context.operation_id,
            user_id=context.principal.user_id,
            original_grant_id=context.principal.grant_id,
            agency_id=uuid.UUID(snapshot["agency_id"]),
            broadcast_id=uuid.UUID(snapshot["broadcast_id"]),
            snapshot=snapshot,
            snapshot_hash=snapshot_hash(snapshot),
            revision=1,
            status="prepared",
            prepared_at=now,
            expires_at=now + PLAN_LIFETIME,
        )
        context.session.add(plan)
        await context.session.flush()
        return MCPDatabaseResult(
            {
                "plan_id": str(plan.id),
                "plan_hash": plan.snapshot_hash,
                "plan_revision": plan.revision,
                "expires_at": plan.expires_at.isoformat(),
                "status": "prepared",
                "preview": public_snapshot(snapshot),
                "confirmation_required": True,
                "notice": "Prepared only. Review exact recipients, message, exclusions and hash before confirming. No message has been queued or sent.",
            }
        )

    async def confirm(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        if set(payload) != {"plan_id", "plan_hash", "user_confirmed"} or payload.get("user_confirmed") is not True:
            raise MCPOperationError("invalid_whatsapp_plan")
        plan = await owned_plan(context, uuid.UUID(payload["plan_id"]), lock=True)
        if (plan.snapshot["worker_payload"]["message_type"] == "reminder") != (
            family == "reminder"
        ):
            raise MCPOperationError("invalid_whatsapp_plan")
        if payload["plan_hash"] != plan.snapshot_hash:
            raise MCPOperationError("whatsapp_plan_hash_mismatch")
        if plan.status == "queued":
            return MCPDatabaseResult(
                {
                    "plan_id": str(plan.id),
                    "batch_id": str(plan.batch_id),
                    "status": "queued",
                    "plan_hash": plan.snapshot_hash,
                },
                status="queued",
                workflow_id=plan.batch_id,
            )
        if plan.status != "prepared" or utc(plan.expires_at) <= datetime.now(UTC):
            raise MCPOperationError("whatsapp_plan_expired_or_closed")
        assert plan.original_grant_id is not None
        original = await MCPAuthorizationService(context.session, settings).require_grant(
            plan.original_grant_id, lock=False
        )
        await require_tool_access(context.session, settings, original.id, f"confirm_whatsapp_{family}", "mcp:communicate", lock=False)
        if (
            original.user_id != context.principal.user_id
            or "mcp:communicate" not in original.capabilities
        ):
            raise MCPAuthError("access_denied", 403)
        # Fresh queueing applies the same website validation/claims. Any drift
        # aborts the complete operation savepoint, retaining the prepared plan.
        queued = await (confirm_snapshot or prepare_snapshot)(
            context, plan.snapshot if confirm_snapshot else plan.snapshot["request"], False
        )
        batch_id = uuid.UUID(queued.pop("batch_id"))
        if snapshot_hash(queued) != plan.snapshot_hash:
            raise MCPOperationError("whatsapp_plan_changed")
        now = datetime.now(UTC)
        plan.status, plan.batch_id, plan.confirmed_at = "queued", batch_id, now
        plan.revision += 1
        context.session.add(
            MCPWhatsAppOutboxModel(
                id=uuid.uuid4(),
                plan_id=plan.id,
                batch_id=batch_id,
                status="pending",
                publication_attempts=0,
                next_attempt_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        await context.session.flush()
        return MCPDatabaseResult(
            {
                "plan_id": str(plan.id),
                "batch_id": str(batch_id),
                "status": "queued",
                "plan_hash": plan.snapshot_hash,
            },
            status="queued",
            workflow_id=batch_id,
        )

    async def cancel(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        if set(payload) != {"plan_id"}:
            raise MCPOperationError("invalid_whatsapp_plan")
        plan = await owned_plan(context, uuid.UUID(payload["plan_id"]), lock=True)
        if plan.status not in {"prepared", "queued", "cancelled"}:
            raise MCPOperationError("whatsapp_plan_expired_or_closed")
        if plan.status != "cancelled":
            plan.status, plan.cancelled_at = "cancelled", datetime.now(UTC)
            plan.revision += 1
            if plan.batch_id:
                # Conditional queued-only update: sent/processing/unknown history
                # is retained. The dispatch gate checks plan state before I/O.
                await fail_unclaimed_broadcast_rows(
                    context.session,
                    batch_id=plan.batch_id,
                    error_message="MCP_INTENT_CANCELLED: stopped before provider submission",
                )
                outbox = await context.session.scalar(
                    select(MCPWhatsAppOutboxModel)
                    .where(MCPWhatsAppOutboxModel.plan_id == plan.id)
                    .with_for_update()
                )
                if outbox is not None and outbox.status in {"pending", "published"}:
                    outbox.status, outbox.updated_at = "cancelled", datetime.now(UTC)
            await context.session.flush()
            if plan.batch_id:
                await refresh_mcp_dispatch_progress(context.session, batch_id=plan.batch_id)
        return MCPDatabaseResult(
            {
                "plan_id": str(plan.id),
                "batch_id": str(plan.batch_id) if plan.batch_id else None,
                "status": "cancelled",
                "notice": "Only this intent's work not yet submitted is stopped. Existing attempts, outcomes and recipient membership are retained; inspect receipts for messages already submitted or uncertain.",
            }
        )

    return (
        MCPDatabaseOperation(
            MCPToolPolicy(
                f"prepare_whatsapp_{family}",
                MCPCapability.COMMUNICATE,
                frozenset({"prepare_communication"}),
            ),
            prepare,
            authorize_receipt,
        ),
        MCPDatabaseOperation(
            MCPToolPolicy(
                f"confirm_whatsapp_{family}",
                MCPCapability.COMMUNICATE,
                frozenset({"queue_communication"}),
            ),
            confirm,
            authorize_receipt,
        ),
        MCPDatabaseOperation(
            MCPToolPolicy(
                "cancel_whatsapp_intent",
                MCPCapability.COMMUNICATE,
                frozenset({"cancel_queued_intent"}),
            ),
            cancel,
            authorize_receipt,
        ),
    )
