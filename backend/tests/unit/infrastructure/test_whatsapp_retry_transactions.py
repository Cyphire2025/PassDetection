"""Real async ORM regressions for partial retry and ambiguous publication."""

from __future__ import annotations

import asyncio
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select

from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp import worker_runtime
from app.infrastructure.whatsapp.publication import (
    fail_unclaimed_broadcast_rows,
    publish_whatsapp_task,
)


async def _seed_batch(session, statuses):
    agency_id, group_id, batch_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    now = datetime.now(tz=UTC)
    session.add(WhatsAppBroadcastGroupModel(id=group_id, agency_id=agency_id, name="Test trip"))
    log_ids = []
    for index, status in enumerate(statuses):
        recipient_id, log_id = uuid.uuid4(), uuid.uuid4()
        session.add(
            WhatsAppBroadcastRecipientModel(
                id=recipient_id,
                broadcast_group_id=group_id,
                agency_id=agency_id,
                phone_number=f"+9198765432{index:02}",
                normalized_phone_number=f"+9198765432{index:02}",
            )
        )
        session.add(
            WhatsAppMessageLogModel(
                id=log_id,
                batch_id=batch_id,
                broadcast_group_id=group_id,
                recipient_id=recipient_id,
                agency_id=agency_id,
                message_type="welcome",
                status=status,
                template_name="welcome",
                created_at=now + timedelta(seconds=index),
                provider_message_id="already-delivered" if status == "delivered" else None,
            )
        )
        session.add(
            WhatsAppRecipientMessageStateModel(
                id=uuid.uuid4(),
                batch_id=batch_id,
                broadcast_group_id=group_id,
                recipient_id=recipient_id,
                agency_id=agency_id,
                message_type="welcome",
                status=status,
            )
        )
        log_ids.append(log_id)
    await session.commit()
    return batch_id, log_ids


async def test_retry_skips_accepted_and_interrupted_rows_and_continues_after_rollback(
    db_session, monkeypatch
):
    batch_id, log_ids = await _seed_batch(db_session, ["delivered", "processing", "queued"])

    @asynccontextmanager
    async def session_factory():
        yield db_session

    send = AsyncMock(return_value="wamid.new")
    monkeypatch.setattr(worker_runtime, "AsyncSessionFactory", session_factory)
    monkeypatch.setattr(worker_runtime, "send_whatsapp_template", send)
    kwargs = dict(
        batch_id=str(batch_id),
        message_type="welcome",
        message_content="Trip update",
        passport_link=None,
    )
    await worker_runtime.run_whatsapp_broadcast(**kwargs)
    await worker_runtime.run_whatsapp_broadcast(**kwargs)

    rows = (await db_session.execute(select(WhatsAppMessageLogModel))).scalars().all()
    statuses = {row.id: row.status for row in rows}
    assert [statuses[log_id] for log_id in log_ids] == [
        "delivered",
        "delivery_unknown",
        "submitted",
    ]
    assert send.await_count == 1
    states = (await db_session.execute(select(WhatsAppRecipientMessageStateModel))).scalars().all()
    assert {state.status for state in states} == {"delivered", "delivery_unknown", "submitted"}
    assert (
        next(row for row in rows if row.id == log_ids[0]).provider_message_id == "already-delivered"
    )


async def test_lost_publication_ack_never_releases_processing_or_accepted_rows(db_session):
    batch_id, log_ids = await _seed_batch(
        db_session, ["queued", "processing", "delivered", "delivery_unknown"]
    )
    await fail_unclaimed_broadcast_rows(
        db_session, batch_id=batch_id, error_message="queue unavailable"
    )
    await db_session.commit()
    rows = (
        (
            await db_session.execute(
                select(WhatsAppMessageLogModel).execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    statuses = {row.id: row.status for row in rows}
    assert [statuses[log_id] for log_id in log_ids] == [
        "failed",
        "processing",
        "delivered",
        "delivery_unknown",
    ]
    states = (
        (
            await db_session.execute(
                select(WhatsAppRecipientMessageStateModel).execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    assert {state.status for state in states} == {
        "failed",
        "processing",
        "delivered",
        "delivery_unknown",
    }
    assert all(state.batch_id == batch_id for state in states if state.status != "failed")


async def test_slow_broker_publication_leaves_event_loop_responsive():
    released = threading.Event()
    calls = []

    def publish(**kwargs):
        calls.append(kwargs)
        assert released.wait(timeout=1), "broker publication blocked the event loop"

    timer = asyncio.get_running_loop().call_later(0.02, released.set)
    try:
        await publish_whatsapp_task(
            SimpleNamespace(apply_async=publish), payload={"batch_id": "test"}
        )
    finally:
        released.set()
        timer.cancel()
    assert calls == [{"kwargs": {"batch_id": "test"}, "queue": "whatsapp"}]
