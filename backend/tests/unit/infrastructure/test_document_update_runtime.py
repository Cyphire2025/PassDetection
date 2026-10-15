"""Text update delivery uses current scope and immutable non-media snapshots."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infrastructure.database.models import (
    WhatsAppBroadcastGroupModel,
    WhatsAppMessageLogModel,
    WhatsAppProviderMessageBindingModel,
)
from app.infrastructure.database.whatsapp_send_intent_models import WhatsAppSendIntentModel
from app.infrastructure.whatsapp import document_update_runtime as runtime
from app.infrastructure.whatsapp import tasks, web_publication
from app.infrastructure.whatsapp.cloud_api_provider import (
    WhatsAppCloudApiError,
    send_whatsapp_document_update_template,
)
from tests.unit.infrastructure.test_document_delivery_slices import _seed


async def seed_update(db_session, monkeypatch, lane="visa"):
    _, deliveries, _, _ = await _seed(db_session, monkeypatch)
    document_delivery = deliveries[0]
    log = WhatsAppMessageLogModel(
        id=uuid.uuid4(),
        batch_id=uuid.uuid4(),
        agency_id=document_delivery.agency_id,
        broadcast_group_id=document_delivery.broadcast_group_id,
        recipient_id=document_delivery.recipient_id,
        message_type="document_update",
        normalized_phone_number=document_delivery.normalized_phone_number,
        status="queued",
        template_name="pending_v1",
        template_language="en",
        header_parameter_values=[],
        template_parameter_values=["Your document is being processed."],
        document_update_context={
            "group_id": str(document_delivery.group_id),
            "document_type": lane,
            "passenger_ids": [str(document_delivery.passenger_id)],
        },
    )
    db_session.add(log)
    await db_session.commit()
    monkeypatch.setattr(
        runtime, "AsyncSessionFactory", async_sessionmaker(db_session.bind, expire_on_commit=False)
    )
    monkeypatch.setattr(
        runtime, "get_settings", lambda: SimpleNamespace(whatsapp_phone_number_id="fixture-account")
    )
    send = AsyncMock(return_value="wamid.update-" + uuid.uuid4().hex)
    monkeypatch.setattr(runtime, "send_whatsapp_document_update_template", send)
    return log, document_delivery, send


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "lane",
    [
        "visa",
        "flight_ticket",
        "flight_ticket_arrival",
        "flight_ticket_domestic",
        "flight_ticket_domestic_arrival",
    ],
)
async def test_all_lanes_send_frozen_text_once_and_record_receipt_binding(
    db_session, monkeypatch, lane
):
    log, document_delivery, send = await seed_update(db_session, monkeypatch, lane)
    assert await runtime.run_document_update_broadcast(batch_id=str(log.batch_id)) == 0
    await db_session.refresh(log)
    assert log.status == "submitted"
    assert send.await_args.kwargs["template_name"] == "pending_v1"
    assert send.await_args.kwargs["language_code"] == "en"
    assert send.await_args.kwargs["message_content"] == "Your document is being processed."
    binding = await db_session.scalar(
        select(WhatsAppProviderMessageBindingModel).where(
            WhatsAppProviderMessageBindingModel.source_id == log.id,
        )
    )
    assert binding.source_kind == "broadcast"
    assert await runtime.run_document_update_broadcast(batch_id=str(log.batch_id)) == 0
    send.assert_awaited_once()
    await db_session.refresh(document_delivery)
    assert document_delivery.status == "queued"


@pytest.mark.asyncio
async def test_no_longer_needed_update_is_skipped_without_resending_document(
    db_session, monkeypatch
):
    log, delivery, send = await seed_update(db_session, monkeypatch)
    delivery.status = "submitted"
    await db_session.commit()
    await runtime.run_document_update_broadcast(batch_id=str(log.batch_id))
    await db_session.refresh(log)
    assert log.status == "skipped"
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoked_broadcast_consent_blocks_queued_update(db_session, monkeypatch):
    log, _, send = await seed_update(db_session, monkeypatch)
    group = await db_session.get(WhatsAppBroadcastGroupModel, log.broadcast_group_id)
    group.recipient_opt_in_confirmed_at = None
    await db_session.commit()
    await runtime.run_document_update_broadcast(batch_id=str(log.batch_id))
    await db_session.refresh(log)
    assert log.status == "failed"
    assert "AUDIENCE_CHANGED" in log.error_message
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_destination_policy_reason_blocks_even_when_identity_and_phone_match(db_session, monkeypatch):
    log, _, send = await seed_update(db_session, monkeypatch)
    original_loader = runtime.load_traveller_destinations

    async def blocked_loader(*args, **kwargs):
        return [replace(row, reason="Contact needs review") for row in await original_loader(*args, **kwargs)]

    monkeypatch.setattr(runtime, "load_traveller_destinations", blocked_loader)
    await runtime.run_document_update_broadcast(batch_id=str(log.batch_id))
    await db_session.refresh(log)
    assert log.status == "failed"
    assert "AUDIENCE_CHANGED" in log.error_message
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_unknown_is_never_automatically_sent_again(db_session, monkeypatch):
    log, _, send = await seed_update(db_session, monkeypatch)
    send.side_effect = WhatsAppCloudApiError("uncertain", delivery_unknown=True)
    await runtime.run_document_update_broadcast(batch_id=str(log.batch_id))
    await runtime.run_document_update_broadcast(batch_id=str(log.batch_id))
    await db_session.refresh(log)
    assert log.status == "delivery_unknown"
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_recent_processing_waits_and_old_interruption_is_unknown(db_session, monkeypatch):
    log, _, send = await seed_update(db_session, monkeypatch)
    log.status = "processing"
    log.status_updated_at = datetime.now(UTC)
    await db_session.commit()
    assert await runtime.run_document_update_broadcast(batch_id=str(log.batch_id)) == 30
    log.status_updated_at = datetime.now(UTC) - timedelta(minutes=12)
    await db_session.commit()
    assert await runtime.run_document_update_broadcast(batch_id=str(log.batch_id)) == 0
    await db_session.refresh(log)
    assert log.status == "delivery_unknown"
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_pending_template_payload_has_exactly_one_body_and_no_media():
    client = SimpleNamespace(
        post=AsyncMock(
            return_value=SimpleNamespace(
                status_code=200,
                json=lambda: {"messages": [{"id": "wamid.update"}]},
            )
        )
    )
    settings = SimpleNamespace(
        whatsapp_access_token="test", whatsapp_phone_number_id="test", whatsapp_api_version="v25.0"
    )
    await send_whatsapp_document_update_template(
        client=client,
        settings=settings,
        to_number="+919876543210",
        template_name="pending_v1",
        language_code="en",
        message_content="Please wait for your visa.",
    )
    assert client.post.await_args.kwargs["json"]["template"] == {
        "name": "pending_v1",
        "language": {"code": "en"},
        "components": [
            {"type": "body", "parameters": [{"type": "text", "text": "Please wait for your visa."}]}
        ],
    }


@pytest.mark.asyncio
async def test_durable_publication_uses_update_task_and_strips_routing_marker(
    db_session, monkeypatch
):
    log, _, send = await seed_update(db_session, monkeypatch)
    intent = WhatsAppSendIntentModel(
        id=uuid.uuid4(),
        agency_id=log.agency_id,
        broadcast_id=log.broadcast_group_id,
        idempotency_hash="a" * 64,
        request_hash="b" * 64,
        initial_response={},
        worker_payload={"batch_id": str(log.batch_id), "message_type": "document_update"},
        batch_id=log.batch_id,
        publication_status="pending",
    )
    db_session.add(intent)
    await db_session.commit()
    monkeypatch.setattr(
        web_publication,
        "AsyncSessionFactory",
        async_sessionmaker(db_session.bind, expire_on_commit=False),
    )
    publish = AsyncMock()
    monkeypatch.setattr(web_publication, "publish_whatsapp_task", publish)
    assert await web_publication.run_whatsapp_send_publication(intent_id=intent.id) == 1
    publish.assert_awaited_once_with(
        tasks.process_document_update_broadcast, payload={"batch_id": str(log.batch_id)}
    )
    await db_session.refresh(intent)
    assert intent.worker_payload["message_type"] == "document_update"
    assert intent.publication_status == "published"
    send.assert_not_awaited()


def test_update_task_publishes_same_batch_with_bounded_limits(monkeypatch):
    def close_and_return(coroutine):
        coroutine.close()
        return 1

    monkeypatch.setattr(tasks, "celery_async_runtime", SimpleNamespace(run=close_and_return))
    enqueue = MagicMock()
    monkeypatch.setattr(tasks.process_document_update_broadcast, "apply_async", enqueue)
    tasks.process_document_update_broadcast(batch_id="frozen-batch")
    enqueue.assert_called_once_with(kwargs={"batch_id": "frozen-batch"}, countdown=1)
    assert tasks.process_document_update_broadcast.soft_time_limit == 540
    assert tasks.process_document_update_broadcast.time_limit == 600


@pytest.mark.asyncio
async def test_known_provider_acceptance_persistence_recovery_never_sends_twice(
    db_session, monkeypatch
):
    log, _, send = await seed_update(db_session, monkeypatch)
    original_binding = runtime.bind_source_provider_message
    calls = 0

    async def failing_first_binding(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated connection failure after provider accepted")
        await original_binding(*args, **kwargs)

    monkeypatch.setattr(runtime, "bind_source_provider_message", failing_first_binding)
    await runtime.run_document_update_broadcast(batch_id=str(log.batch_id))
    await db_session.refresh(log)
    assert log.status == "submitted"
    assert calls == 2
    send.assert_awaited_once()
    await runtime.run_document_update_broadcast(batch_id=str(log.batch_id))
    send.assert_awaited_once()
