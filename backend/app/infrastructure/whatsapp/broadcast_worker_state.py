"""Durable ledger transitions and bounded batch recovery; caller owns callbacks."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database.models import (
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)

ACCEPTED_DELIVERY_STATUSES = frozenset({"submitted", "sent", "delivered", "read"})


@dataclass(frozen=True, slots=True)
class BroadcastStateCallbacks:
    sync_welcome: Callable[..., Awaitable[None]]
    refresh_progress: Callable[..., Awaitable[None]]


async def _set_message_state(
    session: AsyncSession,
    *,
    log: WhatsAppMessageLogModel,
    expected_batch_id: uuid.UUID,
    state_status: str,
    release_claim: bool = False,
    submitted: bool = False,
    callbacks: BroadcastStateCallbacks,
) -> None:
    if log.message_type == "welcome":
        await callbacks.sync_welcome(session, log)
    if getattr(log, "is_explicit_resend", False):
        return
    now = datetime.now(tz=UTC)
    values: dict[str, object] = {
        "status": state_status,
        "status_updated_at": now,
        "updated_at": now,
    }
    if release_claim:
        values["batch_id"] = None
    if submitted:
        values["submitted_at"] = now
        values["batch_id"] = expected_batch_id
    predicates = [
        WhatsAppRecipientMessageStateModel.recipient_id == log.recipient_id,
        WhatsAppRecipientMessageStateModel.message_type == log.message_type,
    ]
    if submitted:
        if log.message_type in {"reminder", "update", "passport_link"}:
            # An earlier reminder completing late must not consume a newer
            # deliberate reminder's claim or move its delivery timestamps.
            predicates.append(WhatsAppRecipientMessageStateModel.batch_id == expected_batch_id)
        # Provider acceptance is authoritative even if removal or stale-claim
        # recovery changed the ledger while the HTTP request was in flight.
        # Never regress a more advanced accepted state.
        predicates.append(
            ~WhatsAppRecipientMessageStateModel.status.in_(ACCEPTED_DELIVERY_STATUSES)
        )
    else:
        predicates.append(WhatsAppRecipientMessageStateModel.batch_id == expected_batch_id)
        if release_claim or state_status == "delivery_unknown":
            predicates.append(
                ~WhatsAppRecipientMessageStateModel.status.in_(ACCEPTED_DELIVERY_STATUSES)
            )
    await session.execute(
        update(WhatsAppRecipientMessageStateModel)
        .where(*predicates)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    await callbacks.refresh_progress(session, batch_id=expected_batch_id)


async def _heartbeat_queued_batch_claims(
    session: AsyncSession,
    *,
    batch_id: uuid.UUID,
    heartbeat_at: datetime,
) -> None:
    """Keep an actively processed large batch out of stale-claim recovery."""

    await session.execute(
        update(WhatsAppMessageLogModel)
        .where(
            WhatsAppMessageLogModel.batch_id == batch_id,
            WhatsAppMessageLogModel.status == "queued",
        )
        .values(status_updated_at=heartbeat_at)
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(WhatsAppRecipientMessageStateModel)
        .where(
            WhatsAppRecipientMessageStateModel.batch_id == batch_id,
            WhatsAppRecipientMessageStateModel.status == "queued",
        )
        .values(
            status_updated_at=heartbeat_at,
            updated_at=heartbeat_at,
        )
        .execution_options(synchronize_session=False)
    )
    await session.commit()


async def mark_whatsapp_batch_failed(
    *,
    batch_id: str,
    error_message: str,
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
    set_message_state: Callable[..., Awaitable[None]],
) -> None:
    """Move any stranded queued rows to a terminal state after retries are exhausted."""

    async with session_factory() as session:
        result = await session.execute(
            select(WhatsAppMessageLogModel)
            .where(
                WhatsAppMessageLogModel.batch_id == uuid.UUID(batch_id),
                WhatsAppMessageLogModel.status.in_(["queued", "processing"]),
            )
            .order_by(
                WhatsAppMessageLogModel.agency_id,
                WhatsAppMessageLogModel.normalized_phone_number,
                WhatsAppMessageLogModel.id,
            )
        )
        for log in result.scalars().all():
            was_processing = log.status == "processing"
            log.status = "delivery_unknown" if was_processing else "failed"
            log.status_updated_at = datetime.now(tz=UTC)
            log.error_message = (
                (f"{error_message}; delivery outcome is unknown and automatic resend is suppressed")
                if was_processing
                else error_message
            )[:2000]
            await set_message_state(
                session,
                log=log,
                expected_batch_id=uuid.UUID(batch_id),
                state_status="delivery_unknown" if was_processing else "failed",
                release_claim=not was_processing,
            )
        await session.commit()
