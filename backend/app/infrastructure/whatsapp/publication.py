"""Nonblocking publication and conservative compensation for durable send rows."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.infrastructure.database.models import (
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)


async def publish_whatsapp_task(task: Any, *, payload: dict[str, object]) -> None:
    """Use the bounded ASGI thread limiter for synchronous broker I/O.

    Callers persist send intent before publication. Broker acknowledgement may
    be lost after acceptance, so failure compensation only releases rows that
    no worker has claimed, never an in-flight provider request.
    """

    await run_in_threadpool(task.apply_async, kwargs=payload, queue="whatsapp")


async def fail_unclaimed_broadcast_rows(
    session: AsyncSession, *, batch_id: uuid.UUID, error_message: str
) -> None:
    """Atomically fail still-queued intent without regressing concurrent sends."""

    now = datetime.now(tz=UTC)
    result = await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.batch_id == batch_id,
            WhatsAppMessageLogModel.status == "queued",
        )
        .values(status="failed", status_updated_at=now, error_message=error_message)
        .returning(WhatsAppMessageLogModel.recipient_id)
        .execution_options(synchronize_session=False)
    )
    recipient_ids = list(result.scalars().all())
    if not recipient_ids:
        return
    await session.execute(
        update(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.batch_id == batch_id,
            WhatsAppRecipientMessageStateModel.recipient_id.in_(recipient_ids),
            WhatsAppRecipientMessageStateModel.status == "queued",
        )
        .values(status="failed", batch_id=None, status_updated_at=now, updated_at=now)
        .execution_options(synchronize_session=False)
    )
