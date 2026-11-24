"""Exercise the actual remote fixture reader with synthetic Redis/database I/O."""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from redis.asyncio import Redis


class Database:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    async def execute(self, _query):
        return SimpleNamespace(all=lambda: [("idle", None, 1)], one=lambda: (0, None))

    async def scalar(self, _query):
        return 100


class RedisClient:
    def __init__(self):
        self.closed = False
        self.entered_read = asyncio.Event()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.closed = True

    async def llen(self, _queue):
        self.entered_read.set()
        await asyncio.Event().wait()


def reader(monkeypatch):
    qa = Path(__file__).resolve().parents[4] / "scripts/qa"
    monkeypatch.syspath_prepend(str(qa))
    importlib.import_module("capacity_fixtures")
    module = importlib.import_module("capacity_fixture_observer")
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: SimpleNamespace(
            redis=SimpleNamespace(broker_url="redis://synthetic.invalid:6379/0"),
        ),
    )
    monkeypatch.setattr(module, "AsyncSessionFactory", Database)
    return module


def test_qa_journey_keeps_the_actual_contact_proof_function_identities(monkeypatch):
    from app.application.security import public_contact_proof

    reader(monkeypatch)
    journey = importlib.import_module("qualification_application_journey")
    assert journey._code_digest is public_contact_proof.code_digest
    assert journey._digest is public_contact_proof.digest


@pytest.mark.asyncio
async def test_remote_reader_has_explicit_redis_connect_and_command_budgets(monkeypatch):
    module = reader(monkeypatch)
    connection = RedisClient()
    factory = Mock(return_value=connection)
    monkeypatch.setattr(Redis, "from_url", factory)
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=Mock(side_effect=[0, 1])))
    await module.observe("0" * 32, seconds=1)
    assert connection.closed
    assert factory.call_args.kwargs["socket_connect_timeout"] == 5
    assert factory.call_args.kwargs["socket_timeout"] == 5


@pytest.mark.asyncio
async def test_remote_reader_deadline_covers_a_stalled_await_without_false_measurements(
    monkeypatch,
):
    module = reader(monkeypatch)
    connection = RedisClient()
    monkeypatch.setattr(Redis, "from_url", lambda *_a, **_kw: connection)
    real_timeout = asyncio.timeout
    budgets = []

    def deadline(seconds):
        budgets.append(seconds)
        return real_timeout(0.01)

    monkeypatch.setattr(module.asyncio, "timeout", deadline)
    printed = Mock()
    monkeypatch.setattr(module, "print", printed, raising=False)
    task = asyncio.create_task(module.observe("0" * 32, seconds=1))
    try:
        await connection.entered_read.wait()
        await asyncio.sleep(0.03)
        assert task.done(), "Nominal duration must bound awaited Redis/database I/O as well"
        with pytest.raises(TimeoutError):
            task.result()
        assert budgets == [11]
        assert connection.closed
        printed.assert_not_called()
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
