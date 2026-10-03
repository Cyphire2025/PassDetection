"""Database-only exact GC notification preparation and enqueue operations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select

from app.application.dtos.gc_notifications import NotificationSendRequest
from app.application.mcp.authorization import MCPAuthorizationService
from app.application.mcp.credentials import MCPAuthError, utc
from app.application.mcp.gc_push_snapshots import (
    GCPushDraft,
    active_agency,
    collect_snapshot,
    digest,
    public_snapshot,
)
from app.application.mcp.operations import (
    MCPCreatedEntity,
    MCPDatabaseContext,
    MCPDatabaseOperation,
    MCPDatabaseResult,
    MCPOperationError,
)
from app.application.mcp.permissions import require_tool_access
from app.application.mobile.authored_notification_preview import create_preview_token
from app.application.mobile.authored_notification_service import send_notification
from app.application.mobile.notification_errors import NotificationWorkflowError
from app.core.config.settings import Settings
from app.domain.mcp_policy import MCPCapability, MCPToolPolicy
from app.infrastructure.database.gc_mobile_models import (
    MobileNotificationModel,
    MobilePushDeliveryModel,
)
from app.infrastructure.database.gc_notification_models import GCNotificationRecipientModel
from app.infrastructure.database.mcp_gc_push_models import MCPGCPushOriginModel, MCPGCPushPlanModel

PLAN_LIFETIME = timedelta(minutes=10)


async def owned_plan(
    context: MCPDatabaseContext, plan_id: uuid.UUID, *, lock: bool = False
) -> MCPGCPushPlanModel:
    statement = select(MCPGCPushPlanModel).where(
        MCPGCPushPlanModel.id == plan_id, MCPGCPushPlanModel.user_id == context.principal.user_id
    )
    if lock:
        statement = statement.with_for_update()
    plan = await context.session.scalar(statement.execution_options(populate_existing=True))
    if plan is None or plan.draft_id is None:
        raise MCPAuthError("access_denied", 403)
    await active_agency(context.session, plan.agency_id)
    return plan


async def _bind_outbox(context: MCPDatabaseContext, plan: MCPGCPushPlanModel) -> None:
    rows = (
        await context.session.execute(
            select(MobileNotificationModel, GCNotificationRecipientModel.person_key)
            .join(
                GCNotificationRecipientModel,
                GCNotificationRecipientModel.id == MobileNotificationModel.authored_recipient_id,
            )
            .where(GCNotificationRecipientModel.batch_id == plan.batch_id)
        )
    ).all()
    now = datetime.now(UTC)
    for notification, person in rows:
        context.session.add(
            MCPGCPushOriginModel(
                notification_id=notification.id,
                batch_id=plan.batch_id,
                plan_id=plan.id,
                created_at=now,
            )
        )
        for device in plan.snapshot["devices"]:
            if device["person_key"] != person:
                continue
            context.session.add(
                MobilePushDeliveryModel(
                    id=uuid.uuid4(),
                    agency_id=plan.agency_id,
                    notification_id=notification.id,
                    registration_id=uuid.UUID(device["registration_id"]),
                    provider=device["provider"],
                    status="retry",
                    send_attempts=0,
                    receipt_attempts=0,
                    next_attempt_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
        if not any(device["person_key"] == person for device in plan.snapshot["devices"]):
            # The exact reviewed audience had no eligible device; a later login
            # cannot silently widen this send. The retained in-app item remains.
            notification.status, notification.failure_code = "failed", "no_active_registration"
    await context.session.flush()


def gc_push_operations(settings: Settings) -> tuple[MCPDatabaseOperation, ...]:
    async def authorize_receipt(context: MCPDatabaseContext, receipt: dict[str, Any]) -> None:
        await owned_plan(context, uuid.UUID(receipt["data"]["plan_id"]))

    async def prepare(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        request = GCPushDraft.model_validate(payload)
        snapshot = await collect_snapshot(context.session, request)
        now = datetime.now(UTC)
        plan = MCPGCPushPlanModel(
            id=uuid.uuid4(),
            operation_id=context.operation_id,
            user_id=context.principal.user_id,
            original_grant_id=context.principal.grant_id,
            agency_id=request.agency_id,
            draft_id=request.draft_id,
            snapshot=snapshot,
            snapshot_hash=digest(snapshot),
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
                "expires_at": plan.expires_at.isoformat(),
                "status": "prepared",
                "preview": public_snapshot(snapshot),
                "confirmation_required": True,
                "notice": "Prepared only. Review the exact content, people and device targets before confirmation. Nothing has been queued or sent.",
            }
        )

    async def confirm(context: MCPDatabaseContext, payload: dict[str, Any]) -> MCPDatabaseResult:
        if set(payload) != {"plan_id", "plan_hash", "user_confirmed"} or payload.get("user_confirmed") is not True:
            raise MCPOperationError("invalid_gc_push_plan")
        plan = await owned_plan(context, uuid.UUID(payload["plan_id"]), lock=True)
        if payload["plan_hash"] != plan.snapshot_hash:
            raise MCPOperationError("gc_push_plan_hash_mismatch")
        if plan.batch_id is not None:
            return _queued(plan)
        if plan.status != "prepared" or utc(plan.expires_at) <= datetime.now(UTC):
            raise MCPOperationError("gc_push_plan_expired_or_closed")
        if plan.original_grant_id is None:
            raise MCPAuthError("access_denied", 403)
        auth = MCPAuthorizationService(context.session, settings)
        original = await auth.require_grant(plan.original_grant_id)
        auth.require_capability(original, MCPCapability.COMMUNICATE.value)
        await require_tool_access(context.session, settings, original.id, "confirm_gc_push", "mcp:communicate", lock=False)
        if original.user_id != context.principal.user_id:
            raise MCPAuthError("access_denied", 403)
        snapshot = await collect_snapshot(
            context.session, GCPushDraft.model_validate(plan.snapshot["request"])
        )
        if digest(snapshot) != plan.snapshot_hash:
            raise MCPOperationError("gc_push_plan_changed")
        assert plan.draft_id is not None
        request = NotificationSendRequest(
            expected_revision=snapshot["draft_revision"],
            request_id=plan.id,
            preview_token=create_preview_token(
                agency_id=plan.agency_id,
                actor_id=context.principal.user_id,
                draft_id=plan.draft_id,
                revision=snapshot["draft_revision"],
                fingerprint=snapshot["audience_fingerprint"],
                expires_at=utc(plan.expires_at),
            ),
        )
        try:
            batch = await send_notification(
                context.session,
                agency_id=plan.agency_id,
                actor_id=context.principal.user_id,
                draft_id=plan.draft_id,
                body=request,
            )
        except NotificationWorkflowError as exc:
            raise MCPOperationError("gc_push_plan_changed") from exc
        plan.status, plan.batch_id, plan.confirmed_at = "queued", batch.id, datetime.now(UTC)
        plan.revision += 1
        await _bind_outbox(context, plan)
        return _queued(plan)

    return tuple(
        MCPDatabaseOperation(
            MCPToolPolicy(name, MCPCapability.COMMUNICATE, frozenset(effects)),
            mutate,
            authorize_receipt,
        )
        for name, effects, mutate in (
            ("prepare_gc_push", {"create_preview"}, prepare),
            ("confirm_gc_push", {"enqueue_communication"}, confirm),
        )
    )


def _queued(plan: MCPGCPushPlanModel) -> MCPDatabaseResult:
    return MCPDatabaseResult(
        {
            "plan_id": str(plan.id),
            "plan_hash": plan.snapshot_hash,
            "batch_id": str(plan.batch_id),
            "status": "queued",
            "notice": "Durable queue acknowledgement only. Provider acceptance is not delivery.",
        },
        status="queued",
        workflow_id=plan.batch_id,
        created_entities=(
            MCPCreatedEntity(
                "gc_notification_batch", str(plan.batch_id), "/gc-app/notifications/history"
            ),
        ),
    )
