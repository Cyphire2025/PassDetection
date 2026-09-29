"""Dispatch observations from retained logs; receipt never implies delivery."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.mcp_communication_models import (
    MCPWhatsAppOutboxModel,
    MCPWhatsAppPlanModel,
)
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import WhatsAppMessageLogModel


async def refresh_mcp_dispatch_progress(session: AsyncSession, *, batch_id: uuid.UUID) -> None:
    """Trusted same-transaction observation only; no authority, queueing or sends.

    Workers call after recording outcomes. Receipt reconciliation may call after
    a later status update, allowing unknown observations to resolve. Initial
    operation receipts stay write-once; completion concerns dispatch processing.
    """
    binding = (
        await session.execute(
            select(MCPWhatsAppOutboxModel.plan_id).where(
                MCPWhatsAppOutboxModel.batch_id == batch_id
            )
        )
    ).first()
    if binding is None:
        return
    await session.flush()
    plan_status = (
        await session.scalar(
            select(MCPWhatsAppPlanModel.status).where(MCPWhatsAppPlanModel.id == binding.plan_id)
        )
        if binding.plan_id
        else "blocked"
    )
    counts = {
        state: int(count)
        for state, count in (
            await session.execute(
                select(WhatsAppMessageLogModel.status, func.count())
                .where(WhatsAppMessageLogModel.batch_id == batch_id)
                .group_by(WhatsAppMessageLogModel.status)
            )
        ).all()
    }
    total = sum(counts.values())
    pending = counts.get("queued", 0) + counts.get("processing", 0)
    known = {"queued", "processing", "submitted", "sent", "delivered", "read", "failed"}
    uncertain = sum(count for state, count in counts.items() if state not in known)
    progress = (total - pending) / total if total else 0.0
    if pending:
        status, stage = (
            "running",
            "dispatch_cancelling" if plan_status == "cancelled" else "dispatching",
        )
    elif uncertain:
        status, stage = (
            "unknown",
            "dispatch_cancelled_unknown" if plan_status == "cancelled" else "dispatch_unknown",
        )
    elif plan_status in {"cancelled", "blocked", None} or not total:
        status, stage = (
            "failed",
            "dispatch_cancelled" if plan_status == "cancelled" else "dispatch_blocked",
        )
    else:
        status, stage = "failed" if counts.get("failed", 0) else "succeeded", "dispatch_complete"
    rows = list(
        (
            await session.scalars(
                select(MCPOperationModel)
                .where(
                    MCPOperationModel.workflow_id == batch_id,
                    MCPOperationModel.operation_name.in_(
                        ["confirm_whatsapp_reminder", "confirm_whatsapp_message"]
                    ),
                )
                .order_by(MCPOperationModel.id)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
        ).all()
    )
    for row in rows:
        # Definitive terminal observations and initial receipts cannot be
        # rewritten. An uncertain provider outcome may later reconcile.
        if row.status in {"succeeded", "failed"} or row.status == "unknown" and status == "running":
            continue
        if row.status == status and row.stage == stage and row.progress == progress:
            continue
        row.status, row.stage, row.progress = status, stage, max(row.progress, progress)
        row.revision += 1
        row.updated_at = datetime.now(UTC)
        row.completed_at = row.updated_at if status in {"succeeded", "failed"} else None
    await session.flush()
