"""Actual ledger safety when a provider attempt fails or acceptance must recover."""

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.infrastructure.database.models import (
    WhatsAppMessageLogModel,
    WhatsAppRecipientMessageStateModel,
)
from app.infrastructure.whatsapp import broadcast_worker_provider, worker_runtime
from app.infrastructure.whatsapp.cloud_api_provider import WhatsAppCloudApiError
from tests.unit.infrastructure.test_whatsapp_retry_transactions import _seed_batch


@pytest.fixture
async def broadcast_work(db_session, monkeypatch):
    batch_id, _ = await _seed_batch(db_session, ["queued"])

    @asynccontextmanager
    async def session_factory():
        yield db_session

    send = AsyncMock(return_value="wamid.accepted")
    sleep = AsyncMock()
    monkeypatch.setattr(worker_runtime, "AsyncSessionFactory", session_factory)
    monkeypatch.setattr(worker_runtime, "send_whatsapp_template", send)
    monkeypatch.setattr(broadcast_worker_provider.asyncio, "sleep", sleep)

    async def run():
        await worker_runtime.run_whatsapp_broadcast(
            batch_id=str(batch_id),
            message_type="welcome",
            message_content="Synthetic update",
            passport_link=None,
        )
        log = (await db_session.execute(select(WhatsAppMessageLogModel))).scalar_one()
        state = (await db_session.execute(select(WhatsAppRecipientMessageStateModel))).scalar_one()
        return log, state

    return send, sleep, run


@pytest.mark.parametrize("outcome", ["unknown", "rejected", "rate_limited", "retry_then_accept"])
async def test_provider_failure_does_not_release_ambiguous_or_accepted_delivery(
    broadcast_work, outcome
):
    send, sleep, run = broadcast_work
    if outcome == "unknown":
        send.side_effect = WhatsAppCloudApiError("safe unknown", delivery_unknown=True)
    elif outcome == "rejected":
        send.side_effect = WhatsAppCloudApiError("safe rejection")
    elif outcome == "rate_limited":
        send.side_effect = WhatsAppCloudApiError("safe rate limit", transient=True)
    else:
        send.side_effect = [
            WhatsAppCloudApiError("safe rate limit", transient=True),
            "wamid.accepted",
        ]

    log, state = await run()
    await run()

    expected = {
        "unknown": "delivery_unknown",
        "rejected": "failed",
        "rate_limited": "failed",
        "retry_then_accept": "submitted",
    }[outcome]
    assert log.status == state.status == expected
    assert (
        send.await_count
        == {"unknown": 1, "rejected": 1, "rate_limited": 3, "retry_then_accept": 2}[outcome]
    )
    assert (
        sleep.await_count
        == {"unknown": 0, "rejected": 0, "rate_limited": 2, "retry_then_accept": 1}[outcome]
    )
    assert (state.batch_id is None) is (expected == "failed")
    if expected == "submitted":
        assert log.provider_message_id == "wamid.accepted"


async def test_known_acceptance_survives_local_binding_rollback_without_resending(
    broadcast_work,
    monkeypatch,
):
    send, _, run = broadcast_work
    original_bind = worker_runtime.bind_source_provider_message
    calls = 0

    async def fail_first_bind(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic-private-DB-detail")
        return await original_bind(*args, **kwargs)

    monkeypatch.setattr(worker_runtime, "bind_source_provider_message", fail_first_bind)
    log, state = await run()
    await run()

    assert calls == 2
    send.assert_awaited_once()
    assert log.status == state.status == "submitted"
    assert log.provider_message_id == "wamid.accepted"
    assert log.error_message is None


async def test_recipient_revocation_during_known_safe_retry_stops_next_send(
    broadcast_work, monkeypatch
):
    send, _, run = broadcast_work
    original_load = worker_runtime._load_sendable_recipient
    checks = 0

    async def revoke_after_first_attempt(*args, **kwargs):
        nonlocal checks
        checks += 1
        if checks >= 3:
            return None, "Destination authorization changed"
        return await original_load(*args, **kwargs)

    monkeypatch.setattr(worker_runtime, "_load_sendable_recipient", revoke_after_first_attempt)
    send.side_effect = WhatsAppCloudApiError("safe rate limit", transient=True)

    log, state = await run()

    send.assert_awaited_once()
    assert log.status == state.status == "failed"
    assert log.error_message == "Destination authorization changed"


@pytest.mark.parametrize("saved", ["invalid-list", ["one", 123]])
async def test_corrupt_frozen_template_fails_before_provider(broadcast_work, db_session, saved):
    send, _, run = broadcast_work
    log = (await db_session.execute(select(WhatsAppMessageLogModel))).scalar_one()
    log.header_parameter_values = ["saved-image"]
    log.template_parameter_values = saved
    await db_session.commit()

    log, state = await run()

    send.assert_not_awaited()
    assert log.status == state.status == "failed"
    assert "Invalid saved WhatsApp template payload" in log.error_message


async def test_superseded_recipient_claim_is_not_consumed_by_old_batch(broadcast_work, db_session):
    send, _, run = broadcast_work
    state = (await db_session.execute(select(WhatsAppRecipientMessageStateModel))).scalar_one()
    newer_batch = uuid.uuid4()
    state.batch_id = newer_batch
    await db_session.commit()

    log, state = await run()

    send.assert_not_awaited()
    assert log.status == "failed"
    assert state.batch_id == newer_batch
    assert state.status == "queued"


async def test_batch_heartbeat_only_refreshes_still_queued_claims(db_session):
    batch_id, _ = await _seed_batch(db_session, ["queued", "processing", "submitted"])
    heartbeat_at = datetime.now(tz=UTC) + timedelta(minutes=6)
    await worker_runtime._heartbeat_queued_batch_claims(
        db_session,
        batch_id=batch_id,
        heartbeat_at=heartbeat_at,
    )
    logs = (await db_session.execute(select(WhatsAppMessageLogModel))).scalars().all()
    states = (await db_session.execute(select(WhatsAppRecipientMessageStateModel))).scalars().all()
    for row in [*logs, *states]:
        # SQLite returns naive datetimes; compare the authoritative UTC value.
        updated = row.status_updated_at.replace(tzinfo=UTC)
        assert (updated == heartbeat_at) is (row.status == "queued")
