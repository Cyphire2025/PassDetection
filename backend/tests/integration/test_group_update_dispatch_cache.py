"""One locked audience per wave, with current source and document state next wave."""

import uuid
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select, update

from app.infrastructure.database.models import WhatsAppMessageLogModel
from app.infrastructure.repositories import passport_whatsapp_comparison_cache as comparison_module
from app.infrastructure.whatsapp import document_update_runtime as runtime
from app.infrastructure.whatsapp import group_update_dispatch as dispatch
from tests.integration.test_document_updates import document
from tests.integration.test_group_updates import group_update as group_update
from tests.integration.test_group_updates import preview, queue, request_for


def log_for(fixture, row, **filters):
    return WhatsAppMessageLogModel(
        id=uuid.uuid4(), agency_id=fixture.agency.id,
        broadcast_group_id=uuid.UUID(row["broadcast_group_id"]),
        recipient_id=uuid.UUID(row["recipient_id"]) if row["recipient_id"] else None,
        normalized_phone_number=row["phone_number"],
        document_update_context={"audience_version": 2, "group_id": str(fixture.group.id),
            "filters": {"submission_status": "all", "document_status": "all",
                        "document_type": "visa", **filters},
            "audience_keys": [row["audience_key"]]},
    )


async def test_same_wave_loads_and_locks_audience_once(group_update, monkeypatch):
    rows = (await preview(group_update))["recipients"]
    loader = AsyncMock(wraps=dispatch.load_group_update_audience)
    monkeypatch.setattr(dispatch, "load_group_update_audience", loader)
    cache = dispatch.GroupUpdateDispatchCache()
    cache.start_wave()
    for row in rows:
        assert await dispatch.group_update_source_decision(
            group_update.session, log_for(group_update, row), cache=cache
        ) == ("processing", None)
    assert loader.await_count == 1
    assert loader.await_args.kwargs["lock"] is True
    group_update.provider.assert_not_awaited()


async def test_next_wave_rereads_document_receipts_without_repeating_matching(group_update, monkeypatch):
    row = (await preview(group_update, submission_status="submitted"))["recipients"][0]
    log = log_for(group_update, row, submission_status="submitted", document_status="pending")
    compare = Mock(wraps=comparison_module.compare_group_submissions)
    monkeypatch.setattr(comparison_module, "compare_group_submissions", compare)
    cache = dispatch.GroupUpdateDispatchCache()
    cache.start_wave()
    assert await dispatch.group_update_source_decision(group_update.session, log, cache=cache) == ("processing", None)
    await group_update.session.commit()
    await document(group_update, 0, status="sent")
    cache.start_wave()
    decision, reason = await dispatch.group_update_source_decision(group_update.session, log, cache=cache)
    assert decision == "skipped" and "AUDIENCE_CHANGED" in reason
    assert compare.call_count == 1
    group_update.provider.assert_not_awaited()


async def test_next_wave_detects_changed_submitted_phone_without_rerouting(group_update, monkeypatch):
    row = (await preview(group_update, submission_status="submitted"))["recipients"][0]
    log = log_for(group_update, row)
    compare = Mock(wraps=comparison_module.compare_group_submissions)
    monkeypatch.setattr(comparison_module, "compare_group_submissions", compare)
    cache = dispatch.GroupUpdateDispatchCache()
    cache.start_wave()
    assert await dispatch.group_update_source_decision(group_update.session, log, cache=cache) == ("processing", None)
    await group_update.session.commit()
    group_update.passengers[0].client_phone = "+919555666777"
    await group_update.session.commit()
    cache.start_wave()
    decision, reason = await dispatch.group_update_source_decision(group_update.session, log, cache=cache)
    assert decision == "skipped" and "AUDIENCE_CHANGED" in reason
    assert compare.call_count == 2
    assert log.normalized_phone_number == row["phone_number"]
    group_update.provider.assert_not_awaited()


async def test_locked_reload_rejects_header_change_after_source_snapshot(group_update, monkeypatch):
    data = await preview(group_update)
    payload = request_for(data)
    payload["audience_keys"] = [data["recipients"][0]["audience_key"]]
    response = (await queue(group_update, payload)).json()
    original_decision = runtime._source_decision

    async def changed_header(session, log, **kwargs):
        result = await original_decision(session, log, **kwargs)
        await session.execute(update(WhatsAppMessageLogModel).where(
            WhatsAppMessageLogModel.id == log.id,
        ).values(header_parameter_values=["unexpected-media"]).execution_options(
            synchronize_session=False,
        ))
        return result

    monkeypatch.setattr(runtime, "_source_decision", changed_header)
    assert await runtime.run_document_update_broadcast(
        batch_id=response["batches"][0]["batch_id"]
    ) == 0
    log = await group_update.session.scalar(select(WhatsAppMessageLogModel))
    assert log.status == "failed" and "SNAPSHOT_CHANGED" in log.error_message
    group_update.provider.assert_not_awaited()


async def test_persistent_acceptance_save_error_does_not_abandon_other_known_results(group_update, monkeypatch):
    response = (await queue(group_update, request_for(await preview(group_update)))).json()
    original_save = runtime._save_provider_result
    blocked_id = None
    attempts = []

    async def failed_one_result(session, log, account):
        nonlocal blocked_id
        attempts.append(log.id)
        if blocked_id is None:
            blocked_id = log.id
        if log.id == blocked_id:
            raise RuntimeError("Synthetic terminal persistence failure")
        await original_save(session, log, account)

    monkeypatch.setattr(runtime, "_save_provider_result", failed_one_result)
    with pytest.raises(RuntimeError, match="terminal persistence"):
        await runtime.run_document_update_broadcast(batch_id=response["batches"][0]["batch_id"])
    logs = list((await group_update.session.scalars(select(WhatsAppMessageLogModel)
        .execution_options(populate_existing=True))).all())
    assert len(attempts) == len(set(attempts)) == 4
    assert sum(log.status == "submitted" and log.provider_message_id is not None for log in logs) == 3
    # The unpersisted acceptance stays processing/uncertain rather than queued.
    assert next(log for log in logs if log.id == blocked_id).status == "processing"
    assert group_update.provider.await_count == 4
