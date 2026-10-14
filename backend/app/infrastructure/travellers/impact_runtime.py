"""Two bounded worker slots, durable page retries and committed feed publishing."""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.travellers.change_feed import publish_change_page
from app.application.travellers.impact import process_impact_page
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.database.traveller_operations_models import IMPACT_QUEUE_FILTER
from app.infrastructure.database.traveller_reuse_models import TravellerChangeEventModel
from app.infrastructure.observability.metrics import metrics


@dataclass(frozen=True, slots=True)
class ImpactClaim:
    event_id: uuid.UUID
    available_at: datetime
    attempt_count: int


async def _reserve(factory: async_sessionmaker[AsyncSession]) -> ImpactClaim | None:
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
        return ImpactClaim(event.id, event.impact_available_at, event.impact_attempt_count)


async def _claimed_event(session: AsyncSession, claim: ImpactClaim) -> TravellerChangeEventModel | None:
    event: TravellerChangeEventModel | None = await session.scalar(select(TravellerChangeEventModel).where(
        TravellerChangeEventModel.id == claim.event_id,
        TravellerChangeEventModel.processed_at.is_(None),
        TravellerChangeEventModel.impact_available_at == claim.available_at,
        TravellerChangeEventModel.impact_attempt_count == claim.attempt_count).with_for_update())
    return event


async def _release(factory: async_sessionmaker[AsyncSession], claim: ImpactClaim) -> None:
    async with factory() as session, session.begin():
        event = await _claimed_event(session, claim)
        if event is not None:
            event.impact_attempt_count -= 1
            event.impact_available_at = datetime.now(UTC) + timedelta(seconds=1)


async def _failed(factory: async_sessionmaker[AsyncSession], claim: ImpactClaim) -> None:
    async with factory() as session, session.begin():
        event = await _claimed_event(session, claim)
        if event is not None:
            event.impact_error_code = "impact_attempts_exhausted" if event.impact_attempt_count >= 5 else "impact_page_failed"
            event.impact_available_at = datetime.now(UTC) + timedelta(seconds=min(300, 5 * 2 ** event.impact_attempt_count))


async def run_impact_tick(*, session_factory: async_sessionmaker[AsyncSession] = AsyncSessionFactory) -> int:
    processed = 0
    for slot in range(2):
        # Reserve durably first, then use the same connection for the global
        # advisory fence and page. No worker needs a second pooled connection.
        claim = await _reserve(session_factory)
        try:
            async with asyncio.timeout(30):
                async with session_factory() as session, session.begin():
                    admitted = await _admitted(session, slot)
                    if admitted and claim is not None:
                        processed += await process_impact_page(session, claim.event_id)
                if not admitted:
                    if claim is not None:
                        await _release(session_factory, claim)
                    continue
                # Publish after the impact page commits, without retaining its
                # row locks. Reacquire the same bounded global processing slot.
                async with session_factory() as session, session.begin():
                    if await _admitted(session, slot):
                        await publish_change_page(session)
        except Exception:
            if claim is not None:
                async with asyncio.timeout(5):
                    await _failed(session_factory, claim)
            metrics.increment("traveller.impact.failures")
    metrics.increment("traveller.impact.processed", processed)
    return processed


async def _admitted(session: AsyncSession, slot: int) -> bool:
    return session.bind is None or session.bind.dialect.name != "postgresql" or bool(
        await session.scalar(text("SELECT pg_try_advisory_xact_lock(913703, :slot)"), {"slot": slot}))
