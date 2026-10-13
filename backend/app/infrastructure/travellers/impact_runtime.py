"""Two bounded worker slots, durable page retries and committed feed publishing."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.travellers.change_feed import publish_change_page
from app.application.travellers.impact import process_impact_page
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.database.traveller_operations_models import IMPACT_QUEUE_FILTER
from app.infrastructure.database.traveller_reuse_models import TravellerChangeEventModel
from app.infrastructure.observability.metrics import metrics


async def _reserve(factory: async_sessionmaker[AsyncSession]) -> uuid.UUID | None:
    async with factory() as session, session.begin():
        event = await session.scalar(select(TravellerChangeEventModel).where(
            text(IMPACT_QUEUE_FILTER),
            TravellerChangeEventModel.impact_available_at <= datetime.now(UTC),
        ).order_by(TravellerChangeEventModel.impact_available_at, TravellerChangeEventModel.id)
            .limit(1).with_for_update(skip_locked=True))
        if event is None:
            return None
        event.impact_attempt_count += 1
        event.impact_available_at = datetime.now(UTC) + timedelta(seconds=60)
        return event.id


async def _failed(factory: async_sessionmaker[AsyncSession], event_id: uuid.UUID) -> None:
    async with factory() as session, session.begin():
        event = await session.scalar(select(TravellerChangeEventModel).where(
            TravellerChangeEventModel.id == event_id,
        ).with_for_update())
        if event is not None and event.processed_at is None:
            event.impact_error_code = "impact_attempts_exhausted" if event.impact_attempt_count >= 5 else "impact_page_failed"
            event.impact_available_at = datetime.now(UTC) + timedelta(seconds=min(300, 5 * 2 ** event.impact_attempt_count))


async def run_impact_tick(*, session_factory: async_sessionmaker[AsyncSession] = AsyncSessionFactory) -> int:
    processed = 0
    for slot in range(2):
        async with session_factory() as admission, admission.begin():
            if admission.bind is not None and admission.bind.dialect.name == "postgresql":
                if not await admission.scalar(text("SELECT pg_try_advisory_xact_lock(913703, :slot)"), {"slot": slot}):
                    continue
            event_id = await _reserve(session_factory)
            try:
                async with asyncio.timeout(30):
                    if event_id is not None:
                        async with session_factory() as session, session.begin():
                            processed += await process_impact_page(session, event_id)
                    async with session_factory() as session, session.begin():
                        await publish_change_page(session)
            except Exception:
                if event_id is not None:
                    await _failed(session_factory, event_id)
                metrics.increment("traveller.impact.failures")
    metrics.increment("traveller.impact.processed", processed)
    return processed
