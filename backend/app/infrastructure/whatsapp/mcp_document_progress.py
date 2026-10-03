"""Observe dispatch completion without claiming provider delivery or retrying."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.mcp_document_delivery_models import MCPDocumentDeliveryOutboxModel
from app.infrastructure.database.mcp_operation_models import MCPOperationModel
from app.infrastructure.database.models import DocumentWhatsAppDeliveryModel


async def document_dispatch_counts(session: AsyncSession, batch_id: uuid.UUID) -> dict[str, int]:
    return {state: int(count) for state, count in (await session.execute(
        select(DocumentWhatsAppDeliveryModel.status, func.count()).where(
            DocumentWhatsAppDeliveryModel.send_batch_id == batch_id,
        ).group_by(DocumentWhatsAppDeliveryModel.status)
    )).all()}


async def refresh_document_dispatch_progress(session: AsyncSession, batch_id: uuid.UUID) -> None:
    binding = await session.scalar(select(MCPDocumentDeliveryOutboxModel.id).where(
        MCPDocumentDeliveryOutboxModel.send_batch_id == batch_id,
    ))
    if not isinstance(binding, uuid.UUID):
        return
    await session.flush()
    counts = await document_dispatch_counts(session, batch_id)
    total, pending = sum(counts.values()), counts.get("queued", 0) + counts.get("processing", 0)
    known = {"queued", "processing", "submitted", "sent", "delivered", "read", "failed"}
    uncertain = sum(count for state, count in counts.items() if state not in known)
    status, stage = (("running", "dispatching") if pending else
                     ("unknown", "dispatch_unknown") if uncertain else
                     ("failed", "dispatch_complete") if not total or counts.get("failed", 0) else
                     ("succeeded", "dispatch_complete"))
    progress = (total - pending) / total if total else 0.0
    rows = (await session.scalars(select(MCPOperationModel).where(
        MCPOperationModel.workflow_id == batch_id,
        MCPOperationModel.operation_name == "confirm_whatsapp_document_delivery",
    ).order_by(MCPOperationModel.id).with_for_update(skip_locked=True)
        .execution_options(populate_existing=True))).all()
    for row in rows:
        if row.status in {"succeeded", "failed"} or row.status == "unknown" and status == "running":
            continue
        if (row.status, row.stage, row.progress) == (status, stage, progress):
            continue
        row.status, row.stage, row.progress = status, stage, max(row.progress, progress)
        row.revision += 1
        row.updated_at = datetime.now(UTC)
        row.completed_at = row.updated_at if status in {"succeeded", "failed"} else None
    await session.flush()
