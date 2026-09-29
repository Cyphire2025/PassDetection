"""Actual normal-send idempotency and duplicate worker/provider serialization."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, func, select

from app.infrastructure.database.mcp_models import MCPGrantModel
from app.infrastructure.database.models import WhatsAppMessageLogModel
from app.infrastructure.database.whatsapp_send_intent_models import WhatsAppSendIntentModel
from app.infrastructure.repositories.user_repository import UserRepository
from app.infrastructure.whatsapp import worker_runtime
from app.presentation.api.v1.routes.whatsapp_send import queue_broadcast_message
from app.presentation.api.v1.routes.whatsapp_send_intents import durable_send
from app.presentation.api.v1.schemas.whatsapp_schemas import WhatsAppSendRequest
from tests.service_integration.test_mcp_concurrency_postgresql import mcp_sessions as mcp_sessions
from tests.service_integration.test_mcp_operations_postgresql import (
    operation_sessions as operation_sessions,
)
from tests.service_integration.test_mcp_whatsapp_postgresql import (
    intent_sessions as intent_sessions,
)

pytestmark = [
    pytest.mark.service_integration,
    pytest.mark.skipif(
        os.getenv("RUN_SERVICE_INTEGRATION") != "1", reason="isolated PostgreSQL required"
    ),
]


async def send(f, *, queue=queue_broadcast_message):
    async with f[0]() as session:
        try:
            grant = await session.get(MCPGrantModel, f[2][0])
            actor = await UserRepository(session).get_by_id(grant.user_id)
            result = await durable_send(
                f[4],
                WhatsAppSendRequest(
                    message_type="reminder", message_content="Exact website repeat"
                ),
                current_user=actor,
                session=session,
                idempotency_key="pg-website-exact-intent",
                queue=queue,
            )
            await session.commit()
            return result
        except BaseException:
            await session.rollback()
            raise


async def test_six_concurrent_normal_sends_return_one_original_batch(intent_sessions):
    f = intent_sessions
    results = await asyncio.wait_for(asyncio.gather(*(send(f) for _ in range(6))), 20)
    assert all(result == results[0] for result in results)
    async with f[0]() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WhatsAppSendIntentModel)
                .where(WhatsAppSendIntentModel.broadcast_id == f[4])
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(WhatsAppMessageLogModel)
                .where(WhatsAppMessageLogModel.batch_id == results[0][0].batch_id)
            )
            == 3
        )


async def test_waiting_send_claim_succeeds_after_winner_database_rollback(intent_sessions):
    f = intent_sessions
    entered, release, waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def fail(*args, **kwargs):
        await queue_broadcast_message(*args, **kwargs)
        entered.set()
        await asyncio.wait_for(release.wait(), 10)
        raise RuntimeError("synthetic failure after queue inserts")

    winner = asyncio.create_task(send(f, queue=fail))
    await asyncio.wait_for(entered.wait(), 5)
    engine = f[0].kw["bind"].sync_engine

    def observe(_connection, _cursor, statement, *_):
        if "FROM users" in statement and "FOR UPDATE" in statement:
            waiting.set()

    event.listen(engine, "before_cursor_execute", observe)
    contender = asyncio.create_task(send(f))
    try:
        await asyncio.wait_for(waiting.wait(), 5)
        assert not contender.done()
        release.set()
        results = await asyncio.wait_for(
            asyncio.gather(winner, contender, return_exceptions=True), 10
        )
        assert isinstance(results[0], RuntimeError) and isinstance(results[1], tuple)
        async with f[0]() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(WhatsAppMessageLogModel)
                    .where(WhatsAppMessageLogModel.broadcast_group_id == f[4])
                )
                == 3
            )
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(WhatsAppSendIntentModel)
                    .where(WhatsAppSendIntentModel.broadcast_id == f[4])
                )
                == 1
            )
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", observe)
        await asyncio.gather(winner, contender, return_exceptions=True)


async def test_duplicate_worker_waits_for_live_provider_then_preserves_known_receipt(
    intent_sessions, monkeypatch
):
    f = intent_sessions
    _, identifier = await send(f)
    async with f[0]() as session:
        intent = await session.get(WhatsAppSendIntentModel, identifier)
        payload = dict(intent.worker_payload)
    entered, release, waiting = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = 0

    async def provider(**_):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await asyncio.wait_for(release.wait(), 10)
        return f"wamid.website.{identifier}.{calls}"

    mock = AsyncMock(side_effect=provider)
    monkeypatch.setattr(worker_runtime, "send_whatsapp_template", mock)
    winner = asyncio.create_task(worker_runtime.run_whatsapp_broadcast(**payload))
    await asyncio.wait_for(entered.wait(), 5)
    engine = f[0].kw["bind"].sync_engine

    def observe(_connection, _cursor, statement, *_):
        if "FROM whatsapp_broadcast_groups" in statement and "FOR UPDATE" in statement:
            waiting.set()

    event.listen(engine, "before_cursor_execute", observe)
    duplicate = asyncio.create_task(worker_runtime.run_whatsapp_broadcast(**payload))
    try:
        await asyncio.wait_for(waiting.wait(), 5)
        assert not duplicate.done()
        release.set()
        await asyncio.wait_for(asyncio.gather(winner, duplicate), 15)
        async with f[0]() as session:
            states = list(
                (
                    await session.scalars(
                        select(WhatsAppMessageLogModel.status).where(
                            WhatsAppMessageLogModel.broadcast_group_id == f[4]
                        )
                    )
                ).all()
            )
            assert states == ["submitted"] * 3
        assert mock.await_count == 3
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", observe)
        await asyncio.gather(winner, duplicate, return_exceptions=True)
