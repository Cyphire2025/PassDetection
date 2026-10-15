"""Real one-connection pools with a simulated transaction-scoped PG fence.

SQLite supplies actual AsyncAdaptedQueuePool admission; only the advisory SQL is
substituted. The same-connection transaction therefore catches the production
deadlock without requiring PostgreSQL for the ordinary unit test suite.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool

from app.infrastructure.travellers import impact_runtime, runtime


class SessionProxy:
    def __init__(self, session, fences):
        self.session, self.fences, self.owned = session, fences, set()
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def __getattr__(self, name):
        return getattr(self.session, name)

    async def get(self, *_args):
        return None

    async def scalar(self, statement, params=None):
        if "pg_try_advisory_xact_lock" not in str(statement):
            return await self.session.scalar(statement, params)
        await self.session.scalar(select(1))  # Actually check out the sole connection.
        key = ("impact" if "913703" in str(statement) else "history", params["slot"])
        if key in self.fences:
            return False
        self.fences.add(key)
        self.owned.add(key)
        return True


def pooled_factory(engine, fences):
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def factory():
        async with sessions() as session:
            proxy = SessionProxy(session, fences)
            try:
                yield proxy
            finally:
                fences.difference_update(proxy.owned)

    return factory


@pytest.mark.asyncio
@pytest.mark.parametrize("workers", [1, 3])
async def test_reconciliation_uses_one_connection_and_at_most_two_global_slots(tmp_path, monkeypatch, workers):
    engines = [create_async_engine(f"sqlite+aiosqlite:///{tmp_path / f'worker-{index}.db'}",
        poolclass=AsyncAdaptedQueuePool, pool_size=1, max_overflow=0, pool_timeout=0.3) for index in range(workers)]
    fences, released = set(), []
    active = peak = processed = 0

    async def reserve(factory):
        async with factory() as session, session.begin():
            assert await session.scalar(select(1)) == 1
        return runtime.ReconciliationClaim(uuid.uuid4(), datetime.now(UTC) + timedelta(seconds=60), 1)

    async def page(session, **_kwargs):
        nonlocal active, peak, processed
        assert await session.scalar(select(1)) == 1
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.03)
        active -= 1
        processed += 1
        return SimpleNamespace(processed=1)

    async def release(factory, claim):
        async with factory() as session, session.begin():
            await session.scalar(select(1))
        released.append(claim.job_id)

    monkeypatch.setattr(runtime, "_reserve_reconciliation", reserve)
    monkeypatch.setattr(runtime, "reconcile_page", page)
    monkeypatch.setattr(runtime, "_release_reconciliation", release)

    async def worker(engine):
        factory = pooled_factory(engine, fences)
        return [await runtime._reconciliation_slot(factory, object(), slot, runtime.monotonic() + 2)
            for slot in range(2)]

    try:
        batches = await asyncio.wait_for(asyncio.gather(*(worker(engine) for engine in engines)), 3)
        results = [result for batch in batches for result in batch]
        assert sum(count for count, _ in results) == processed > 0
        assert processed + len(released) == workers * 2
        assert peak <= 2 and not fences
        if workers == 1:
            assert processed == 2 and not released and peak == 1
    finally:
        for engine in engines:
            await engine.dispose()


@pytest.mark.asyncio
async def test_impact_page_and_feed_publish_with_one_connection(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'impact.db'}",
        poolclass=AsyncAdaptedQueuePool, pool_size=1, max_overflow=0, pool_timeout=0.05)
    fences, commits = set(), []
    factory = pooled_factory(engine, fences)

    async def reserve(factory):
        async with factory() as session, session.begin():
            await session.scalar(select(1))
        commits.append("reserve")
        return impact_runtime.ImpactClaim(uuid.uuid4(), datetime.now(UTC) + timedelta(seconds=60), 1)

    async def process(session, _event_id):
        assert await session.scalar(select(1)) == 1
        commits.append("page")
        return 1

    async def publish(session):
        assert await session.scalar(select(1)) == 1
        commits.append("publish")

    monkeypatch.setattr(impact_runtime, "_reserve", reserve)
    monkeypatch.setattr(impact_runtime, "process_impact_page", process)
    monkeypatch.setattr(impact_runtime, "publish_change_page", publish)
    try:
        assert await asyncio.wait_for(impact_runtime.run_impact_tick(session_factory=factory), 2) == 2
        assert commits == ["reserve", "page", "publish"] * 2
        assert not fences
    finally:
        await engine.dispose()
