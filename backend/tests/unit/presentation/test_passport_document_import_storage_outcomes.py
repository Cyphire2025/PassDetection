"""Real SQLite references and actual Minio/to_thread calls with synthetic S3 IO."""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infrastructure.database.models import (
    AgencyModel,
    ClientGroupModel,
    PassportSubmissionModel,
)
from app.infrastructure.documents import passport_import_compensation as compensation
from app.infrastructure.storage import minio_repository
from app.presentation.api.v1.routes.passport_routes import document_import as route
from app.presentation.api.v1.routes.passport_routes import document_import_failure
from tests.unit.presentation.passport_document_import_fixture import (
    NativeBarrier,
    cancel_held_operation,
    install_import_context,
    invoke,
)


@pytest.fixture
async def persisted_import(db_session, monkeypatch, test_settings):
    agency = AgencyModel(id=uuid.uuid4(), name="Import", email="import@example.test")
    db_session.add(agency)
    await db_session.flush()
    group = ClientGroupModel(
        id=uuid.uuid4(),
        agency_id=agency.id,
        name="Import",
        token=uuid.uuid4().hex,
    )
    db_session.add(group)
    await db_session.flush()
    passenger = PassportSubmissionModel(
        id=uuid.uuid4(),
        group_id=group.id,
        agency_id=agency.id,
        client_name="Synthetic",
        staff_metadata={"staff_code": "A1"},
        status="needs_review",
        image_s3_key="excel-imports/synthetic/placeholder.jpg",
    )
    db_session.add(passenger)
    await db_session.commit()
    context = install_import_context(
        monkeypatch,
        session=db_session,
        group=SimpleNamespace(id=group.id, agency_id=group.agency_id),
        submission=passenger,
    )
    context.passenger_id = passenger.id
    context.group_id = group.id
    context.agency_id = agency.id
    context.factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    context.objects = {}
    context.cleanup = Mock(return_value=())
    monkeypatch.setattr(compensation, "stage_storage_cleanup_jobs", context.cleanup)

    async def reconcile(**kwargs):
        return await compensation.reconcile_failed_passport_import(
            **kwargs,
            session_factory=context.factory,
        )

    context.reconciliation = AsyncMock(side_effect=reconcile)
    monkeypatch.setattr(
        document_import_failure, "reconcile_failed_passport_import", context.reconciliation
    )

    def put(*, Key, Body, **_kwargs):
        context.objects[Key] = Body
        return {}

    context.client = SimpleNamespace(put_object=put)
    monkeypatch.setattr(minio_repository, "get_settings", lambda: test_settings)
    monkeypatch.setattr(
        minio_repository,
        "_shared_s3_clients",
        lambda: (context.client, context.client),
    )
    monkeypatch.setattr(route, "MinioStorageRepository", minio_repository.MinioStorageRepository)
    return context


async def stored_front(context):
    async with context.factory() as fresh:
        return await fresh.scalar(
            select(PassportSubmissionModel.image_s3_key).where(
                PassportSubmissionModel.id == context.passenger_id
            )
        )


@pytest.mark.parametrize("cancel_twice", [False, True])
@pytest.mark.parametrize("provider_error", [False, True])
async def test_cancelled_save_drains_actual_put_then_reconciles_uncommitted_key(
    monkeypatch,
    persisted_import,
    cancel_twice,
    provider_error,
):
    context = persisted_import
    original_put = context.client.put_object

    def put(**kwargs):
        if provider_error:
            raise OSError("Synthetic late PUT failure")
        return original_put(**kwargs)

    barrier = NativeBarrier(put)
    monkeypatch.setattr(context.client, "put_object", barrier)
    task = asyncio.create_task(invoke(context, "save"))
    returned_early = await cancel_held_operation(task, barrier, twice=cancel_twice)
    assert not returned_early, "Save returned while its real boto PUT was still held"
    assert await stored_front(context) == "excel-imports/synthetic/placeholder.jpg"
    context.reconciliation.assert_awaited_once()
    assert not context.reconciliation.await_args.kwargs["commit_attempted"]
    keys = context.reconciliation.await_args.kwargs["uploaded_keys"]
    assert len(keys) == 1
    assert context.cleanup.call_args.kwargs["storage_keys"] == keys
    assert list(context.objects.values()) == (
        [] if provider_error else [b"canonical:synthetic-source"]
    )
    assert context.workspaces[0]._closed


@pytest.mark.parametrize(
    "outcome",
    [
        "ordinary",
        "before-commit-error",
        "lost-ack-error",
        "before-commit-cancel",
        "lost-ack-cancel",
    ],
)
async def test_save_commit_outcomes_use_fresh_committed_references(
    monkeypatch,
    persisted_import,
    outcome,
):
    context = persisted_import
    original_commit = context.session.commit

    async def commit():
        if outcome in {"ordinary", "lost-ack-error", "lost-ack-cancel"}:
            await original_commit()
        if outcome.endswith("error"):
            raise ConnectionError("Synthetic commit acknowledgement failure")
        if outcome.endswith("cancel"):
            raise asyncio.CancelledError("Synthetic cancellation at commit boundary")

    monkeypatch.setattr(context.session, "commit", commit)
    if outcome == "ordinary":
        assert (await invoke(context, "save")).saved_count == 1
    elif outcome.endswith("error"):
        with pytest.raises(HTTPException) as failure:
            await invoke(context, "save")
        assert failure.value.status_code == 503
    else:
        with pytest.raises(asyncio.CancelledError):
            await invoke(context, "save")
    key = next(iter(context.objects))
    persisted = await stored_front(context)
    committed = outcome == "ordinary" or outcome.startswith("lost-ack")
    assert persisted == (key if committed else "excel-imports/synthetic/placeholder.jpg")
    assert context.objects[key] == b"canonical:synthetic-source"
    if outcome == "ordinary":
        context.reconciliation.assert_not_awaited()
        context.cleanup.assert_not_called()
    else:
        context.reconciliation.assert_awaited_once()
        assert context.reconciliation.await_args.kwargs["commit_attempted"]
        assert context.cleanup.call_args.kwargs["storage_keys"] == ([] if committed else [key])
    assert context.workspaces[0]._closed


async def test_second_cancellation_cannot_abandon_rollback_and_reference_inspection(
    monkeypatch,
    persisted_import,
):
    context = persisted_import
    entered, release = asyncio.Event(), asyncio.Event()
    original_reconcile = context.reconciliation.side_effect

    async def reconcile(**kwargs):
        entered.set()
        await release.wait()
        return await original_reconcile(**kwargs)

    context.reconciliation.side_effect = reconcile
    monkeypatch.setattr(
        context.session,
        "commit",
        AsyncMock(side_effect=asyncio.CancelledError),
    )
    task = asyncio.create_task(invoke(context, "save"))
    try:
        await asyncio.wait_for(entered.wait(), 0.2)
        task.cancel()
        await asyncio.wait({task}, timeout=0.03)
        returned_early = task.done()
    finally:
        release.set()
        outcomes = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 3)
    assert isinstance(outcomes[0], asyncio.CancelledError)
    assert not returned_early
    assert context.cleanup.call_args.kwargs["storage_keys"] == list(context.objects)


async def test_rollback_failure_still_performs_fresh_reference_inspection(
    monkeypatch,
    persisted_import,
):
    context = persisted_import
    original_rollback = context.session.rollback
    rollback_count = 0

    async def rollback():
        nonlocal rollback_count
        rollback_count += 1
        await original_rollback()
        if rollback_count == 2:
            raise ConnectionError("Synthetic rollback acknowledgement failure")

    monkeypatch.setattr(context.session, "rollback", rollback)
    monkeypatch.setattr(context.session, "commit", AsyncMock(side_effect=ConnectionError))
    with pytest.raises(ConnectionError, match="rollback acknowledgement"):
        await invoke(context, "save")
    context.reconciliation.assert_awaited_once()
    assert context.cleanup.call_args.kwargs["storage_keys"] == list(context.objects)
    assert context.workspaces[0]._closed
