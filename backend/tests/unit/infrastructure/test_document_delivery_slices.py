"""Provider-free database regression tests for resumable document broadcasts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infrastructure.database.models import (
    DistributedDocumentModel,
    DocumentDistributionBatchModel,
    DocumentWhatsAppDeliveryModel,
)
from app.infrastructure.whatsapp import document_delivery_runtime as runtime
from tests.persistence import persist_graph
from tests.unit.infrastructure.test_private_delivery_policy import (
    PHONE,
    _document_delivery,
    _seed_private_delivery_context,
)


async def _seed(db_session, monkeypatch, *, count=1):
    context = await _seed_private_delivery_context(db_session)
    passenger = context["passengers"][0]
    passenger.client_phone = PHONE
    batch = DocumentDistributionBatchModel(
        id=uuid.uuid4(),
        agency_id=context["agency"].id,
        group_id=context["group"].id,
        document_type="visa",
        status="saved",
    )
    batch_id = uuid.uuid4()
    documents, deliveries = [], []
    for index in range(count):
        document = DistributedDocumentModel(
            id=uuid.uuid4(),
            batch_id=batch.id,
            agency_id=context["agency"].id,
            group_id=context["group"].id,
            passenger_id=passenger.id,
            document_type="visa",
            original_filename=f"visa-{index}.pdf",
            storage_key=f"test/visa-{index}.pdf",
            match_status="matched",
        )
        delivery = _document_delivery(context, status="queued")
        delivery.send_batch_id = batch_id
        delivery.document_batch_id = batch.id
        delivery.distributed_document_id = document.id
        delivery.created_at = datetime.now(UTC) + timedelta(microseconds=index)
        documents.append(document)
        deliveries.append(delivery)
    await persist_graph(db_session, [batch, *documents, *deliveries])
    await db_session.commit()
    monkeypatch.setattr(
        runtime,
        "AsyncSessionFactory",
        async_sessionmaker(
            db_session.bind,
            expire_on_commit=False,
        ),
    )
    monkeypatch.setattr(
        runtime,
        "get_settings",
        lambda: SimpleNamespace(
            whatsapp_delivery_concurrency=4,
            whatsapp_phone_number_id="fixture-account",
        ),
    )
    storage = AsyncMock(return_value=b"%PDF-1.7 synthetic fixture")
    monkeypatch.setattr(
        runtime, "MinioStorageRepository", lambda: SimpleNamespace(get_file=storage)
    )
    upload = AsyncMock(return_value="fixture-media")
    monkeypatch.setattr(runtime, "upload_whatsapp_document", upload)
    send = AsyncMock(side_effect=lambda **kwargs: "wamid." + uuid.uuid4().hex)
    monkeypatch.setattr(runtime, "send_whatsapp_document_template", send)
    monkeypatch.setattr(
        runtime, "_propagate_first_released_document_batch", AsyncMock(return_value=0)
    )
    return batch_id, deliveries, upload, send


@pytest.mark.asyncio
async def test_700_deliveries_continue_in_bounded_slices_without_duplicates(
    db_session, monkeypatch
):
    batch_id, deliveries, upload, send = await _seed(db_session, monkeypatch, count=700)
    # Model one earlier uncertain and one already accepted send. Neither may be
    # sent again by a continuation or by a duplicate task publication.
    deliveries[0].status = "delivery_unknown"
    deliveries[1].status = "submitted"
    await db_session.commit()
    slice_sizes = []
    while True:
        previous = send.await_count
        delay = await runtime.run_document_whatsapp_broadcast(send_batch_id=str(batch_id))
        slice_sizes.append(send.await_count - previous)
        assert slice_sizes[-1] <= runtime.DOCUMENT_DELIVERY_SLICE_SIZE
        if not delay:
            break
        assert len(slice_sizes) <= 28
    assert len(slice_sizes) == 28
    assert send.await_count == upload.await_count == 698
    assert await runtime.run_document_whatsapp_broadcast(send_batch_id=str(batch_id)) == 0
    assert send.await_count == 698
    counts = dict(
        (
            await db_session.execute(
                select(
                    DocumentWhatsAppDeliveryModel.status,
                    func.count(),
                ).group_by(DocumentWhatsAppDeliveryModel.status)
            )
        ).all()
    )
    assert counts == {"submitted": 699, "delivery_unknown": 1}


@pytest.mark.asyncio
async def test_slice_deadline_requeues_uploaded_but_unsent_document(db_session, monkeypatch):
    batch_id, deliveries, upload, send = await _seed(db_session, monkeypatch)
    clock = [0.0]
    monkeypatch.setattr(runtime, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    async def upload_over_budget(**kwargs):
        clock[0] = runtime.DOCUMENT_DELIVERY_SLICE_SECONDS + 1
        return "fixture-media"

    upload.side_effect = upload_over_budget
    assert await runtime.run_document_whatsapp_broadcast(send_batch_id=str(batch_id)) == 1
    send.assert_not_awaited()
    await db_session.refresh(deliveries[0])
    assert deliveries[0].status == "queued"
    upload.side_effect = None
    assert await runtime.run_document_whatsapp_broadcast(send_batch_id=str(batch_id)) == 0
    send.assert_awaited_once()
    await db_session.refresh(deliveries[0])
    assert deliveries[0].status == "submitted"


@pytest.mark.asyncio
async def test_live_processing_is_preserved_and_stale_interruption_is_unknown(
    db_session, monkeypatch
):
    batch_id, deliveries, upload, send = await _seed(db_session, monkeypatch)
    deliveries[0].status = "processing"
    deliveries[0].status_updated_at = datetime.now(UTC)
    await db_session.commit()
    assert await runtime.run_document_whatsapp_broadcast(send_batch_id=str(batch_id)) == 30
    await db_session.refresh(deliveries[0])
    assert deliveries[0].status == "processing"
    deliveries[0].status_updated_at = datetime.now(UTC) - timedelta(minutes=12)
    await db_session.commit()
    assert await runtime.run_document_whatsapp_broadcast(send_batch_id=str(batch_id)) == 0
    await db_session.refresh(deliveries[0])
    assert deliveries[0].status == "delivery_unknown"
    upload.assert_not_awaited()
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_inflight_send_finishes_after_admission_deadline_without_cancellation(
    db_session, monkeypatch
):
    batch_id, deliveries, upload, send = await _seed(db_session, monkeypatch)
    clock = [0.0]
    monkeypatch.setattr(runtime, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    async def slow_send(**kwargs):
        clock[0] = runtime.DOCUMENT_DELIVERY_SLICE_SECONDS + 1
        return "wamid.finished-after-admission"

    send.side_effect = slow_send
    assert await runtime.run_document_whatsapp_broadcast(send_batch_id=str(batch_id)) == 0
    await db_session.refresh(deliveries[0])
    assert deliveries[0].status == "submitted"
    assert deliveries[0].provider_message_id == "wamid.finished-after-admission"


def test_task_publishes_same_batch_continuation_only_when_pending(monkeypatch):
    from app.infrastructure.whatsapp import tasks

    def run_and_close(coroutine):
        coroutine.close()
        return 1

    monkeypatch.setattr(tasks.celery_async_runtime, "run", run_and_close)
    publication = MagicMock()
    monkeypatch.setattr(tasks.process_document_whatsapp_broadcast, "apply_async", publication)
    identifier = str(uuid.uuid4())
    tasks.process_document_whatsapp_broadcast.run(send_batch_id=identifier)
    publication.assert_called_once_with(kwargs={"send_batch_id": identifier}, countdown=1)

    def complete(coroutine):
        coroutine.close()
        return 0

    monkeypatch.setattr(tasks.celery_async_runtime, "run", complete)
    tasks.process_document_whatsapp_broadcast.run(send_batch_id=identifier)
    assert publication.call_count == 1
