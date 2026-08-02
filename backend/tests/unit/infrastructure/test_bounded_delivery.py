"""Bounded delivery fan-out tests with synthetic provider handlers."""

from __future__ import annotations

import asyncio
import uuid
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from app.infrastructure.whatsapp.bounded_delivery import run_bounded_delivery_items
from app.infrastructure.whatsapp.document_delivery_runtime import (
    _document_media_source_statement,
    _locked_document_batches_statement,
    _locked_document_source_statement,
    run_document_whatsapp_broadcast,
)
from app.infrastructure.whatsapp.qr_delivery_runtime import (
    _qr_media_source_statement,
    run_qr_whatsapp_broadcast,
)


def test_document_batch_fence_locks_all_batches_once_and_children_lock_only_docs() -> None:
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    batch_ids = {uuid.uuid4(), uuid.uuid4()}
    batch_sql = str(
        _locked_document_batches_statement(
            document_batch_ids=batch_ids,
            agency_id=agency_id,
            group_id=group_id,
        ).compile(dialect=postgresql.dialect())
    )
    delivery = SimpleNamespace(
        distributed_document_id=uuid.uuid4(),
        document_batch_id=next(iter(batch_ids)),
        agency_id=agency_id,
        group_id=group_id,
        passenger_id=uuid.uuid4(),
        document_type="visa",
    )
    child_sql = str(
        _locked_document_source_statement(delivery, batch_fenced=True).compile(
            dialect=postgresql.dialect()
        )
    )

    assert "document_distribution_batches.id IN" in batch_sql
    assert "ORDER BY document_distribution_batches.id" in batch_sql
    assert batch_sql.endswith("FOR UPDATE")
    assert "FOR UPDATE OF distributed_documents" in child_sql
    assert "FOR UPDATE OF document_distribution_batches" not in child_sql


def test_private_media_reads_require_ledger_tenant_and_passenger_parity() -> None:
    document_sql = str(
        _document_media_source_statement(
            delivery_id=uuid.uuid4(),
            send_batch_id=uuid.uuid4(),
        ).compile(dialect=postgresql.dialect())
    )
    qr_sql = str(
        _qr_media_source_statement(
            delivery_id=uuid.uuid4(),
            send_batch_id=uuid.uuid4(),
        ).compile(dialect=postgresql.dialect())
    )

    assert (
        "distributed_documents.agency_id = document_whatsapp_deliveries.agency_id"
        in document_sql
    )
    assert (
        "distributed_documents.group_id = document_whatsapp_deliveries.group_id"
        in document_sql
    )
    assert (
        "distributed_documents.passenger_id = "
        "document_whatsapp_deliveries.passenger_id"
        in document_sql
    )
    assert "document_distribution_batches.status =" in document_sql
    assert (
        "distributed_documents.document_type = "
        "document_whatsapp_deliveries.document_type"
        in document_sql
    )
    assert (
        "document_distribution_batches.document_type = "
        "document_whatsapp_deliveries.document_type"
        in document_sql
    )
    assert "client_groups.deleted_at IS NULL" in document_sql
    assert (
        "passenger_qr_tokens.agency_id = "
        "passenger_qr_whatsapp_deliveries.agency_id"
        in qr_sql
    )
    assert (
        "passenger_qr_tokens.passenger_id = "
        "passenger_qr_whatsapp_deliveries.passenger_id"
        in qr_sql
    )


@pytest.mark.asyncio
async def test_bounded_four_is_faster_than_serial_with_peak_four() -> None:
    active = 0
    peak = 0

    async def synthetic_provider(_item: int) -> None:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        active -= 1

    started = perf_counter()
    for item in range(12):
        await synthetic_provider(item)
    serial_elapsed = perf_counter() - started

    active = 0
    peak = 0
    started = perf_counter()
    await run_bounded_delivery_items(
        list(range(12)),
        synthetic_provider,
        concurrency=4,
    )
    bounded_elapsed = perf_counter() - started

    assert peak == 4
    assert bounded_elapsed < serial_elapsed * 0.65


@pytest.mark.asyncio
async def test_transient_429_retries_remain_inside_worker_ceiling() -> None:
    active = 0
    peak = 0
    attempts: dict[int, int] = {}

    async def synthetic_retrying_provider(item: int) -> None:
        nonlocal active, peak
        for _attempt in range(2):
            active += 1
            peak = max(peak, active)
            attempts[item] = attempts.get(item, 0) + 1
            await asyncio.sleep(0.005)
            active -= 1
            if attempts[item] == 1:  # Synthetic HTTP 429; retry in this worker.
                await asyncio.sleep(0)
                continue
            return

    await run_bounded_delivery_items(
        list(range(16)),
        synthetic_retrying_provider,
        concurrency=4,
    )

    assert peak <= 4
    assert set(attempts.values()) == {2}


@pytest.mark.asyncio
async def test_one_item_failure_does_not_cancel_siblings() -> None:
    completed: set[int] = set()

    async def sometimes_fails(item: int) -> None:
        await asyncio.sleep(0)
        if item == 3:
            raise RuntimeError("synthetic provider failure")
        completed.add(item)

    with pytest.raises(RuntimeError, match="synthetic provider failure"):
        await run_bounded_delivery_items(
            list(range(10)),
            sometimes_fails,
            concurrency=4,
        )

    assert completed == set(range(10)) - {3}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runner", "module_path"),
    [
        (
            run_document_whatsapp_broadcast,
            "app.infrastructure.whatsapp.document_delivery_runtime",
        ),
        (
            run_qr_whatsapp_broadcast,
            "app.infrastructure.whatsapp.qr_delivery_runtime",
        ),
    ],
)
async def test_batch_runtimes_use_bounded_hard_capped_fanout(
    runner: object,
    module_path: str,
) -> None:
    delivery_ids = [uuid.uuid4() for _ in range(20)]
    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    document_batch_ids = [uuid.uuid4(), uuid.uuid4()]
    batch_rows = [
        SimpleNamespace(
            id=delivery_id,
            agency_id=agency_id,
            group_id=group_id,
            document_batch_id=document_batch_ids[index % 2],
        )
        for index, delivery_id in enumerate(delivery_ids)
    ]
    rows_result = MagicMock()
    rows_result.all.return_value = batch_rows
    batch_lock_result = MagicMock()
    batch_lock_result.scalars.return_value.all.return_value = document_batch_ids
    session = AsyncMock()
    session.execute.side_effect = (
        [rows_result, batch_lock_result]
        if "document_delivery_runtime" in module_path
        else [rows_result]
    )
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)
    bounded_runner = AsyncMock()
    source_snapshot = SimpleNamespace()
    source_locker = AsyncMock(return_value=source_snapshot)

    with (
        patch(f"{module_path}.AsyncSessionFactory", return_value=session_context),
        patch(
            f"{module_path}.get_settings",
            return_value=SimpleNamespace(whatsapp_delivery_concurrency=99),
        ),
        patch(f"{module_path}.run_bounded_delivery_items", bounded_runner),
        patch(
            f"{module_path}.lock_private_delivery_group_source_snapshot",
            source_locker,
        ),
    ):
        await runner(send_batch_id=str(uuid.uuid4()))

    assert bounded_runner.await_args.args[0] == delivery_ids
    assert bounded_runner.await_args.kwargs["concurrency"] == 16
    source_locker.assert_awaited_once_with(
        session,
        agency_id=agency_id,
        group_id=group_id,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("runner", "module_path", "runner_name"),
    [
        (
            run_document_whatsapp_broadcast,
            "app.infrastructure.whatsapp.document_delivery_runtime",
            "run_document_whatsapp_broadcast",
        ),
        (
            run_qr_whatsapp_broadcast,
            "app.infrastructure.whatsapp.qr_delivery_runtime",
            "run_qr_whatsapp_broadcast",
        ),
    ],
)
async def test_batch_source_fence_allows_four_child_provider_windows_to_overlap(
    runner: object,
    module_path: str,
    runner_name: str,
) -> None:
    """Synthetic child/provider timing proves the coordinator does not serialize."""

    agency_id = uuid.uuid4()
    group_id = uuid.uuid4()
    delivery_ids = [uuid.uuid4() for _ in range(8)]
    document_batch_ids = [uuid.uuid4(), uuid.uuid4()]
    rows_result = MagicMock()
    rows_result.all.return_value = [
        SimpleNamespace(
            id=item,
            agency_id=agency_id,
            group_id=group_id,
            document_batch_id=document_batch_ids[index % 2],
        )
        for index, item in enumerate(delivery_ids)
    ]
    batch_lock_result = MagicMock()
    batch_lock_result.scalars.return_value.all.return_value = document_batch_ids
    session = AsyncMock()
    session.execute.side_effect = (
        [rows_result, batch_lock_result]
        if "document_delivery_runtime" in module_path
        else [rows_result]
    )
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=False)
    snapshot = SimpleNamespace()
    active = 0
    peak = 0
    completed: list[uuid.UUID] = []
    shared_clients: set[int] = set()

    async def synthetic_child_provider(
        *,
        send_batch_id: str,
        _delivery_id: uuid.UUID,
        _source_snapshot: object,
        _client: object,
    ) -> None:
        del send_batch_id
        nonlocal active, peak
        assert _source_snapshot is snapshot
        shared_clients.add(id(_client))
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.02)
        completed.append(_delivery_id)
        active -= 1

    with (
        patch(f"{module_path}.AsyncSessionFactory", return_value=session_context),
        patch(
            f"{module_path}.get_settings",
            return_value=SimpleNamespace(whatsapp_delivery_concurrency=4),
        ),
        patch(
            f"{module_path}.lock_private_delivery_group_source_snapshot",
            new=AsyncMock(return_value=snapshot),
        ),
        patch(f"{module_path}.{runner_name}", side_effect=synthetic_child_provider),
    ):
        await runner(send_batch_id=str(uuid.uuid4()))

    assert peak == 4
    assert set(completed) == set(delivery_ids)
    assert len(shared_clients) == 1
