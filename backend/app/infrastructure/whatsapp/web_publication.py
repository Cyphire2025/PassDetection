"""Recover website broker publication using the retained original batch only."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.infrastructure.database.models import WhatsAppMessageLogModel
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.database.whatsapp_send_intent_models import WhatsAppSendIntentModel
from app.infrastructure.whatsapp.publication import (
    fail_unclaimed_broadcast_rows,
    publish_whatsapp_task,
)

RESERVATION = timedelta(minutes=5)
MAX_ATTEMPTS = 12


async def reserve_send_publication(identifier: uuid.UUID) -> dict[str, Any] | None:
    async with AsyncSessionFactory() as session:
        intent = await session.scalar(
            select(WhatsAppSendIntentModel)
            .where(WhatsAppSendIntentModel.id == identifier)
            .with_for_update()
        )
        now = datetime.now(UTC)
        if (
            intent is None
            or intent.publication_status not in {"pending", "published"}
            or intent.batch_id is None
        ):
            return None
        due = (
            intent.next_attempt_at.replace(tzinfo=UTC)
            if intent.next_attempt_at.tzinfo is None
            else intent.next_attempt_at
        )
        if due > now:
            return None
        counts = {
            state: int(count)
            for state, count in (
                await session.execute(
                    select(WhatsAppMessageLogModel.status, func.count())
                    .where(WhatsAppMessageLogModel.batch_id == intent.batch_id)
                    .group_by(WhatsAppMessageLogModel.status)
                )
            ).all()
        }
        if not counts.get("queued", 0) and not counts.get("processing", 0):
            intent.publication_status = "completed"
            intent.next_attempt_at, intent.updated_at = now + RESERVATION, now
            await session.commit()
            return None
        if intent.publication_attempts >= MAX_ATTEMPTS:
            intent.publication_status, intent.last_error_code = (
                "blocked",
                "publication_attempt_limit",
            )
            intent.updated_at = now
            await fail_unclaimed_broadcast_rows(
                session,
                batch_id=intent.batch_id,
                error_message="WHATSAPP_QUEUE_UNAVAILABLE: publication attempts exhausted before provider submission",
            )
            await session.commit()
            return None
        intent.publication_attempts += 1
        intent.next_attempt_at, intent.updated_at = now + RESERVATION, now
        payload = dict(intent.worker_payload)
        await session.commit()
        return payload


async def run_whatsapp_send_publication(
    *, limit: int = 20, intent_id: uuid.UUID | None = None
) -> int:
    if not 1 <= limit <= 100:
        raise ValueError("Publication limit must be 1 to 100")
    async with AsyncSessionFactory() as session:
        stmt = select(WhatsAppSendIntentModel.id).where(
            WhatsAppSendIntentModel.publication_status.in_(["pending", "published"]),
            WhatsAppSendIntentModel.next_attempt_at <= datetime.now(UTC),
        )
        if intent_id is not None:
            stmt = stmt.where(WhatsAppSendIntentModel.id == intent_id)
        ids = list(
            (
                await session.scalars(
                    stmt.order_by(
                        WhatsAppSendIntentModel.next_attempt_at, WhatsAppSendIntentModel.id
                    ).limit(limit)
                )
            ).all()
        )
    from app.infrastructure.whatsapp.tasks import process_whatsapp_broadcast

    published = 0
    for identifier in ids:
        payload = await reserve_send_publication(identifier)
        if payload is None:
            continue
        failed = False
        try:
            await publish_whatsapp_task(process_whatsapp_broadcast, payload=payload)
        except Exception:
            failed = True
        async with AsyncSessionFactory() as session:
            intent = await session.scalar(
                select(WhatsAppSendIntentModel)
                .where(WhatsAppSendIntentModel.id == identifier)
                .with_for_update()
            )
            if intent is not None and intent.publication_status in {"pending", "published"}:
                intent.publication_status = "pending" if failed else "published"
                intent.last_error_code = "broker_unavailable_or_uncertain" if failed else None
                intent.updated_at = datetime.now(UTC)
                await session.commit()
        if not failed:
            published += 1
    return published
