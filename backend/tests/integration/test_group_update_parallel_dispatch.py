"""Real queued update dispatch, with provider calls isolated behind async barriers."""

import asyncio
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from app.infrastructure.database.models import (
    PassportSubmissionModel,
    WhatsAppBroadcastRecipientModel,
    WhatsAppMessageLogModel,
    WhatsAppProviderMessageBindingModel,
)
from app.infrastructure.repositories import (
    passport_whatsapp_comparison_cache,
    passport_whatsapp_matching_repository,
)
from app.infrastructure.whatsapp import (
    document_update_provider_wave,
    document_update_runtime,
    group_update_dispatch,
)
from app.infrastructure.whatsapp.cloud_api_provider import WhatsAppCloudApiError
from tests.integration.test_document_updates import document
from tests.integration.test_group_updates import (
    group_update as group_update,
)
from tests.integration.test_group_updates import (
    preview,
    queue,
    request_for,
)
from tests.persistence import persist_graph


async def _expand_roster(fixture, count, *, submitted=False):
    new_rows = []
    for index in range(len(fixture.recipients), count):
        recipient = WhatsAppBroadcastRecipientModel(
            id=uuid.uuid4(), agency_id=fixture.agency.id,
            broadcast_group_id=fixture.broadcast.id, name=f"Contact {index}",
            phone_number=f"+9198765432{index:02}",
            normalized_phone_number=f"+9198765432{index:02}",
            imported_fields={"staff_code": f"EMP{index}"},
        )
        fixture.recipients.append(recipient)
        new_rows.append(recipient)
    if submitted:
        for index in range(len(fixture.passengers), count):
            passenger = PassportSubmissionModel(
                id=uuid.uuid4(), agency_id=fixture.agency.id, group_id=fixture.group.id,
                client_name=f"Person {index}", client_phone=f"+9191234567{index:02}",
                client_reviewed_at=datetime.now(UTC),
                staff_metadata={"staff_code": f"EMP{index}"}, image_s3_key="test/passport",
                status="staff_approved",
            )
            fixture.passengers.append(passenger)
            new_rows.append(passenger)
    await persist_graph(fixture.session, new_rows)


async def _queued_batch(fixture, **filters):
    response = await queue(fixture, request_for(await preview(fixture, **filters)))
    return response.json()["batches"][0]["batch_id"]


async def _logs(fixture):
    return list((await fixture.session.scalars(
        select(WhatsAppMessageLogModel).execution_options(populate_existing=True)
    )).all())


async def test_provider_requests_overlap_four_at_a_time_and_resume_without_resending(group_update):
    await _expand_roster(group_update, 9)
    batch = await _queued_batch(group_update)
    ready = [asyncio.Event() for _ in range(3)]
    release = [asyncio.Event() for _ in range(3)]
    entered = []
    active = 0
    peak_active = 0

    async def provider(**kwargs):
        nonlocal active, peak_active
        index = len(entered)
        entered.append(kwargs["to_number"])
        active += 1
        peak_active = max(peak_active, active)
        assert active <= 4
        if len(entered) in (4, 8, 9):
            ready[index // 4].set()
        try:
            await release[index // 4].wait()
            return "wamid.parallel." + uuid.uuid4().hex
        finally:
            active -= 1

    group_update.provider.side_effect = provider
    task = asyncio.create_task(document_update_runtime.run_document_update_broadcast(batch_id=batch))
    try:
        for wave, expected in enumerate((4, 8, 9)):
            await asyncio.wait_for(ready[wave].wait(), timeout=5)
            assert len(entered) == expected
            assert active == (4 if wave < 2 else 1)
            release[wave].set()
    finally:
        for event in release:
            event.set()
        await asyncio.wait_for(task, timeout=15)

    assert peak_active == 4
    assert len(set(entered)) == 9
    assert Counter(log.status for log in await _logs(group_update)) == {"submitted": 9}
    assert await document_update_runtime.run_document_update_broadcast(batch_id=batch) == 0
    assert group_update.provider.await_count == 9


@pytest.mark.parametrize("unknown_error", [
    WhatsAppCloudApiError("Uncertain response", delivery_unknown=True),
    TimeoutError("Provider request timed out"),
])
async def test_rejected_or_uncertain_request_does_not_cancel_accepted_siblings(group_update, unknown_error):
    batch = await _queued_batch(group_update)
    started = asyncio.Event()
    call_count = 0
    rejected_phone = group_update.passengers[0].client_phone
    unknown_phone = group_update.passengers[1].client_phone

    async def provider(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 4:
            started.set()
        await started.wait()
        if kwargs["to_number"] == rejected_phone:
            raise WhatsAppCloudApiError("Provider declined", code="131049")
        if kwargs["to_number"] == unknown_phone:
            raise unknown_error
        return "wamid.sibling." + uuid.uuid4().hex

    group_update.provider.side_effect = provider
    await asyncio.wait_for(document_update_runtime.run_document_update_broadcast(batch_id=batch), timeout=10)
    logs = {log.normalized_phone_number: log for log in await _logs(group_update)}
    assert Counter(log.status for log in logs.values()) == {
        "submitted": 2, "failed": 1, "delivery_unknown": 1,
    }
    assert logs[rejected_phone].error_message.startswith("131049:")
    assert logs[unknown_phone].provider_message_id is None
    assert all(log.provider_message_id for log in logs.values() if log.status == "submitted")
    assert await document_update_runtime.run_document_update_broadcast(batch_id=batch) == 0
    assert group_update.provider.await_count == 4


async def test_known_acceptances_all_survive_one_binding_rollback(group_update, monkeypatch):
    batch = await _queued_batch(group_update)
    real_binding = document_update_runtime.bind_source_provider_message
    attempts = 0

    async def transient_binding_failure(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("Synthetic persistence interruption after provider acceptance")
        await real_binding(*args, **kwargs)

    monkeypatch.setattr(document_update_runtime, "bind_source_provider_message", transient_binding_failure)
    assert await document_update_runtime.run_document_update_broadcast(batch_id=batch) == 0
    logs = await _logs(group_update)
    assert Counter(log.status for log in logs) == {"submitted": 4}
    assert len({log.provider_message_id for log in logs}) == 4
    bindings = list((await group_update.session.scalars(select(WhatsAppProviderMessageBindingModel))).all())
    assert {binding.source_id for binding in bindings} == {log.id for log in logs}
    assert {binding.provider_message_id for binding in bindings} == {log.provider_message_id for log in logs}
    assert await document_update_runtime.run_document_update_broadcast(batch_id=batch) == 0
    assert group_update.provider.await_count == 4


async def test_unrecoverable_binding_error_still_saves_other_acceptances_and_never_resends(group_update, monkeypatch):
    batch = await _queued_batch(group_update)
    failed_id = (await _logs(group_update))[0].id
    real_binding = document_update_runtime.bind_source_provider_message

    async def broken_binding(session, log, **kwargs):
        if log.id == failed_id:
            raise RuntimeError("Synthetic durable binding outage")
        await real_binding(session, log, **kwargs)

    monkeypatch.setattr(document_update_runtime, "bind_source_provider_message", broken_binding)
    with pytest.raises(RuntimeError, match="Synthetic durable binding outage"):
        await document_update_runtime.run_document_update_broadcast(batch_id=batch)
    logs = await _logs(group_update)
    assert Counter(log.status for log in logs) == {"submitted": 3, "processing": 1}
    assert len({log.provider_message_id for log in logs if log.provider_message_id}) == 3
    assert await document_update_runtime.run_document_update_broadcast(batch_id=batch) == 30
    assert group_update.provider.await_count == 4


async def test_provider_deadline_makes_only_timed_out_recipient_uncertain(group_update, monkeypatch):
    batch = await _queued_batch(group_update)
    slow_phone = group_update.passengers[0].client_phone
    never_released = asyncio.Event()
    monkeypatch.setattr(document_update_provider_wave, "PROVIDER_ATTEMPT_DEADLINE_SECONDS", 0.02)

    async def provider(**kwargs):
        if kwargs["to_number"] == slow_phone:
            await never_released.wait()
        return "wamid.bounded." + uuid.uuid4().hex

    group_update.provider.side_effect = provider
    assert await asyncio.wait_for(document_update_runtime.run_document_update_broadcast(batch_id=batch), timeout=10) == 0
    logs = {log.normalized_phone_number: log for log in await _logs(group_update)}
    assert Counter(log.status for log in logs.values()) == {"submitted": 3, "delivery_unknown": 1}
    assert logs[slow_phone].status == "delivery_unknown"
    assert await document_update_runtime.run_document_update_broadcast(batch_id=batch) == 0
    assert group_update.provider.await_count == 4


async def test_25_row_slice_reuses_full_comparison_when_exact_inputs_unchanged(group_update, monkeypatch):
    await _expand_roster(group_update, 25)
    batch = await _queued_batch(group_update)
    comparison = Mock(wraps=passport_whatsapp_matching_repository.compare_group_submissions)
    monkeypatch.setattr(passport_whatsapp_matching_repository, "compare_group_submissions", comparison)
    monkeypatch.setattr(passport_whatsapp_comparison_cache, "compare_group_submissions", comparison)
    audience_load = AsyncMock(wraps=group_update_dispatch.load_group_update_audience)
    monkeypatch.setattr(group_update_dispatch, "load_group_update_audience", audience_load)
    assert await document_update_runtime.run_document_update_broadcast(batch_id=batch) == 0
    assert group_update.provider.await_count == 25
    assert comparison.call_count == 1
    assert audience_load.await_count == 7
    assert Counter(log.status for log in await _logs(group_update)) == {"submitted": 25}


@pytest.mark.parametrize("change", ["phone", "document"])
async def test_next_wave_rechecks_current_phone_and_document_filter(group_update, monkeypatch, change):
    await _expand_roster(group_update, 8, submitted=True)
    batch = await _queued_batch(group_update, submission_status="submitted", document_status="pending")
    ordered = list((await group_update.session.scalars(
        select(WhatsAppMessageLogModel)
        .order_by(WhatsAppMessageLogModel.created_at, WhatsAppMessageLogModel.id)
    )).all())
    target = ordered[4]
    target_id = target.id
    old_phone = target.normalized_phone_number
    passenger_id = uuid.UUID(target.document_update_context["audience_keys"][0].split(":", 1)[1])
    passenger_index = next(index for index, item in enumerate(group_update.passengers) if item.id == passenger_id)
    real_save = document_update_runtime._save_provider_result
    persisted = 0

    async def save_then_change_source(*args, **kwargs):
        nonlocal persisted
        await real_save(*args, **kwargs)
        persisted += 1
        if persisted == 4:
            if change == "phone":
                group_update.passengers[passenger_index].client_phone = "+919555888777"
                await group_update.session.commit()
            else:
                await document(group_update, passenger_index, status="sent")

    monkeypatch.setattr(document_update_runtime, "_save_provider_result", save_then_change_source)
    assert await document_update_runtime.run_document_update_broadcast(batch_id=batch) == 0
    logs = {log.id: log for log in await _logs(group_update)}
    assert logs[target_id].status == "skipped"
    assert "UPDATE_AUDIENCE_CHANGED" in logs[target_id].error_message
    assert Counter(log.status for log in logs.values()) == {"submitted": 7, "skipped": 1}
    sent_phones = {call.kwargs["to_number"] for call in group_update.provider.await_args_list}
    assert old_phone not in sent_phones
    assert "+919555888777" not in sent_phones
    assert group_update.provider.await_count == 7


async def test_continuation_resumes_only_remaining_rows_after_25_row_slice(group_update):
    await _expand_roster(group_update, 30)
    batch = await _queued_batch(group_update)
    assert await document_update_runtime.run_document_update_broadcast(batch_id=batch) == 1
    assert Counter(log.status for log in await _logs(group_update)) == {"submitted": 25, "queued": 5}
    first_sent = {call.kwargs["to_number"] for call in group_update.provider.await_args_list}
    assert len(first_sent) == 25
    assert await document_update_runtime.run_document_update_broadcast(batch_id=batch) == 0
    all_sent = [call.kwargs["to_number"] for call in group_update.provider.await_args_list]
    assert len(all_sent) == len(set(all_sent)) == 30
    assert Counter(log.status for log in await _logs(group_update)) == {"submitted": 30}


async def test_slice_deadline_stops_before_next_wave_and_retains_pending_jobs(group_update, monkeypatch):
    await _expand_roster(group_update, 9)
    batch = await _queued_batch(group_update)
    clock = [0.0]
    monkeypatch.setattr(document_update_runtime, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    calls = 0

    async def provider(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 4:
            clock[0] = document_update_runtime.DOCUMENT_DELIVERY_SLICE_SECONDS + 1
        return "wamid.deadline." + uuid.uuid4().hex

    group_update.provider.side_effect = provider
    assert await document_update_runtime.run_document_update_broadcast(batch_id=batch) == 1
    assert calls == 4
    assert Counter(log.status for log in await _logs(group_update)) == {"submitted": 4, "queued": 5}
    assert await document_update_runtime.run_document_update_broadcast(batch_id=batch) == 0
    assert group_update.provider.await_count == 9
    assert Counter(log.status for log in await _logs(group_update)) == {"submitted": 9}


async def test_interrupted_processing_becomes_uncertain_without_automatic_resend(group_update):
    batch = await _queued_batch(group_update)
    logs = await _logs(group_update)
    now = datetime.now(UTC)
    logs[0].status = "processing"
    logs[0].status_updated_at = now - document_update_runtime.DOCUMENT_DELIVERY_STALE_AFTER - timedelta(seconds=1)
    logs[1].status = "processing"
    logs[1].status_updated_at = now
    logs[2].status = "submitted"
    logs[2].provider_message_id = "wamid.already.accepted"
    fresh_id = logs[1].id
    queued_phone = logs[3].normalized_phone_number
    await group_update.session.commit()
    assert await document_update_runtime.run_document_update_broadcast(batch_id=batch) == 30
    assert Counter(log.status for log in await _logs(group_update)) == {
        "delivery_unknown": 1, "processing": 1, "submitted": 2,
    }
    group_update.provider.assert_awaited_once()
    assert group_update.provider.await_args.kwargs["to_number"] == queued_phone
    fresh = next(log for log in await _logs(group_update) if log.id == fresh_id)
    fresh.status_updated_at = now - document_update_runtime.DOCUMENT_DELIVERY_STALE_AFTER - timedelta(seconds=1)
    await group_update.session.commit()
    assert await document_update_runtime.run_document_update_broadcast(batch_id=batch) == 0
    assert Counter(log.status for log in await _logs(group_update)) == {"delivery_unknown": 2, "submitted": 2}
    group_update.provider.assert_awaited_once()
