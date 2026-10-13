"""Burst throughput bounds and the PostgreSQL global worker admission fence."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.infrastructure.travellers import runtime


@asynccontextmanager
async def context(value=None):
    yield value


def factory(session=None):
    value = session or SimpleNamespace(begin=context)
    return lambda: context(value)


@pytest.mark.asyncio
async def test_burst_stops_after_40_pages_with_at_most_two_concurrent_slots(monkeypatch):
    running = peak = calls = 0

    async def slot(*args):
        nonlocal running, peak, calls
        running += 1
        peak = max(peak, running)
        calls += 1
        await asyncio.sleep(0)
        running -= 1
        return 25, True

    monkeypatch.setattr(runtime, "advance_company_history_chain", AsyncMock())
    monkeypatch.setattr(runtime, "_reconciliation_slot", slot)
    count = await runtime.run_reconciliation_tick(session_factory=factory(), crypto=object())
    assert (count, calls, peak) == (1000, 40, 2)


@pytest.mark.asyncio
async def test_deadline_rechecked_before_admitting_another_page(monkeypatch):
    clock = [0.0]

    async def slot(*args):
        clock[0] = 51.0
        return 1, True

    advance = AsyncMock()
    monkeypatch.setattr(runtime, "advance_company_history_chain", advance)
    monkeypatch.setattr(runtime, "monotonic", lambda: clock[0])
    monkeypatch.setattr(runtime, "_reconciliation_slot", slot)
    assert await runtime.run_reconciliation_tick(session_factory=factory(), crypto=object()) == 2
    advance.assert_awaited_once()


@pytest.mark.asyncio
async def test_idle_or_denied_slots_end_burst_without_repeated_polling(monkeypatch):
    slot = AsyncMock(return_value=(0, False))
    monkeypatch.setattr(runtime, "advance_company_history_chain", AsyncMock())
    monkeypatch.setattr(runtime, "_reconciliation_slot", slot)
    assert await runtime.run_reconciliation_tick(session_factory=factory(), crypto=object()) == 0
    assert slot.await_count == 2


@pytest.mark.asyncio
async def test_burst_deadline_also_cancels_blocked_admission(monkeypatch):
    cancelled = []

    async def slot(_factory, _crypto, index, _deadline):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(index)

    monkeypatch.setattr(runtime, "RECONCILIATION_BURST_SECONDS", 0.01)
    monkeypatch.setattr(runtime, "advance_company_history_chain", AsyncMock())
    monkeypatch.setattr(runtime, "_reconciliation_slot", slot)
    assert await runtime.run_reconciliation_tick(session_factory=factory(), crypto=object()) == 0
    assert sorted(cancelled) == [0, 1]


@pytest.mark.asyncio
async def test_postgresql_advisory_fence_denial_never_reserves_job(monkeypatch):
    session = SimpleNamespace(begin=context, bind=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
        scalar=AsyncMock(return_value=False))
    reserve = AsyncMock()
    monkeypatch.setattr(runtime, "_reserve_reconciliation", reserve)
    result = await runtime._reconciliation_slot(factory(session), object(), 1, runtime.monotonic() + 10)
    assert result == (0, False)
    reserve.assert_not_awaited()
    assert "pg_try_advisory_xact_lock(913702" in str(session.scalar.call_args.args[0])
    assert session.scalar.call_args.args[1] == {"slot": 1}


@pytest.mark.asyncio
async def test_page_failure_requeues_in_separate_failure_transaction(monkeypatch):
    session = SimpleNamespace(begin=context, bind=None)
    identifier = uuid.uuid4()
    failure = AsyncMock()
    monkeypatch.setattr(runtime, "_reserve_reconciliation", AsyncMock(return_value=identifier))
    monkeypatch.setattr(runtime, "reconcile_page", AsyncMock(side_effect=TimeoutError))
    monkeypatch.setattr(runtime, "_fail_reconciliation", failure)
    result = await runtime._reconciliation_slot(factory(session), object(), 0, runtime.monotonic() + 10)
    assert result == (0, True)
    assert failure.await_args.args[1] == identifier


@pytest.mark.asyncio
async def test_failure_preserves_dirty_refresh_and_clears_lease():
    job = SimpleNamespace(status="running", attempt_count=2, last_error_code=runtime.DIRTY,
        lease_expires_at=object())
    session = SimpleNamespace(begin=context, scalar=AsyncMock(return_value=job))
    await runtime._fail_reconciliation(factory(session), uuid.uuid4())
    assert job.status == "queued" and job.last_error_code == runtime.DIRTY
    assert job.lease_expires_at is None
