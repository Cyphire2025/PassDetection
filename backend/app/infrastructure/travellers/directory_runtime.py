"""One bounded directory consumer; derived rows commit with their checkpoint."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import cast

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.companies.directory_projection import (
    backfill_directory_page,
    refresh_directory_person,
)
from app.core.config.traveller_reuse import get_traveller_reuse_settings
from app.infrastructure.database.company_directory_models import CompanyDirectoryQueueModel as Queue
from app.infrastructure.database.session import AsyncSessionFactory
from app.infrastructure.observability.metrics import metrics
from app.infrastructure.security.traveller_reuse_crypto import (
    ReuseCryptoUnavailable,
    TravellerReuseCrypto,
)


async def _next_person(session: AsyncSession) -> uuid.UUID | None:
    return cast(uuid.UUID | None, await session.scalar(select(Queue.traveller_id).where(
        Queue.available_at <= datetime.now(UTC), Queue.attempt_count < 5)
        .order_by(Queue.available_at, Queue.traveller_id).limit(1)))


async def run_company_directory_tick(*, session_factory: async_sessionmaker[AsyncSession] = AsyncSessionFactory,
    crypto: TravellerReuseCrypto | None = None,
) -> int:
    try:
        crypto = crypto or TravellerReuseCrypto(get_traveller_reuse_settings())
    except ReuseCryptoUnavailable:
        metrics.increment("company.directory.configuration_unavailable")
        return 0
    processed, deadline = 0, monotonic() + 20
    for _ in range(100):
        if monotonic() >= deadline:
            break
        person_id = None
        refreshed = False
        try:
            async with asyncio.timeout(max(0.01, min(5, deadline - monotonic()))):
                async with session_factory() as session, session.begin():
                    if session.get_bind().dialect.name == "postgresql" and not await session.scalar(
                        text("SELECT pg_try_advisory_xact_lock(913703, 0)")):
                        break
                    person_id = await _next_person(session)
                    if person_id is None:
                        await backfill_directory_page(session)
                        person_id = await _next_person(session)
                    if person_id is not None:
                        refreshed = await refresh_directory_person(session, person_id, crypto)
            processed += int(refreshed)
            if person_id is None:
                break
        except Exception as exc:
            metrics.increment("company.directory.refresh_failed")
            if person_id is None:
                break
            async with asyncio.timeout(3):
                async with session_factory() as session, session.begin():
                    row = await session.scalar(select(Queue).where(Queue.traveller_id == person_id).with_for_update())
                    if row is not None:
                        row.attempt_count += 1
                        row.available_at = datetime.now(UTC) + timedelta(seconds=min(300, 5 * 2 ** row.attempt_count))
                        row.last_error_code = type(exc).__name__[:32]
    metrics.increment("company.directory.refreshed", processed)
    return processed
