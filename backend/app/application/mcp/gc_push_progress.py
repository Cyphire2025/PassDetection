"""Mutable push observations; never rewrite the original enqueue receipt."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.mobile.authored_notification_history import batch_responses
from app.infrastructure.database.gc_notification_models import GCNotificationBatchModel
from app.infrastructure.database.mcp_gc_push_models import MCPGCPushOriginModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel


async def refresh_push_progress(
    session: AsyncSession, batch_id: uuid.UUID
) -> dict[str, Any] | None:
    batch = await session.get(GCNotificationBatchModel, batch_id)
    if batch is None:
        return None
    result = (await batch_responses(session, [batch]))[0].model_dump(mode="json")
    devices = result["device_delivery_counts"]
    recipients = result["recipient_counts"]
    pending = devices["submitting"] + devices["retry"]
    unknown = devices["unknown"]
    stage = (
        "provider_outcome_unknown" if unknown else "dispatching" if pending else "dispatch_complete"
    )
    status = "unknown" if unknown else "running" if pending else "succeeded"
    if (
        not pending
        and not unknown
        and not (devices["provider_accepted"] + devices["receipt_pending"] + devices["delivered"])
    ):
        status = "failed"
        stage = "dispatch_blocked_or_failed"
    total = devices["total"]
    progress = 1.0 if not total else (total - pending) / total
    # A confirmation replay holds operation -> plan. Dispatch holds plan ->
    # parents, so observations must never wait on that operation lock. Explicit
    # inspection is the deterministic catch-up path even for terminal batches.
    operations = await session.scalars(
        select(MCPOperationModel)
        .where(
            MCPOperationModel.workflow_id == batch_id,
            MCPOperationModel.operation_name == "confirm_gc_push",
        )
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    for operation in operations:
        if (operation.status, operation.progress, operation.stage) != (status, progress, stage):
            operation.status, operation.progress, operation.stage = status, progress, stage
            operation.revision += 1
            operation.updated_at = datetime.now(UTC)
            operation.completed_at = (
                operation.updated_at if status in {"succeeded", "failed"} else None
            )
    return {
        "batch_id": str(batch_id),
        "stage": stage,
        "status": status,
        "recipient_counts": recipients,
        "device_delivery_counts": devices,
        "completion_scope": "Dispatch completion is not confirmed delivery. Provider acceptance, delivered, failed and unknown are separate.",
    }


async def refresh_notification_progress(
    session: AsyncSession, notification_ids: list[uuid.UUID]
) -> None:
    batches = await session.scalars(
        select(MCPGCPushOriginModel.batch_id)
        .where(MCPGCPushOriginModel.notification_id.in_(notification_ids))
        .distinct()
    )
    for batch_id in batches:
        await refresh_push_progress(session, batch_id)
