"""Ordinary input and infrastructure failures retain ECR resource ownership."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.datastructures import Headers

from app.infrastructure.database.ecr_models import EcrItemModel
from app.infrastructure.security.upload_validator import MalwareScannerUnavailableError
from app.presentation.api.v1.routes import ecr_checker as routes
from app.presentation.api.v1.routes import ecr_checker_upload as uploads
from app.presentation.api.v1.routes.ecr_checker_actions import _dispatch as _real_dispatch
from tests.unit.presentation.test_ecr_checker import _create, _file, _image, _user
from tests.unit.presentation.test_ecr_checker import storage as storage


async def test_scanner_outage_rejects_upload_without_storing_or_accepting_rows(db_session, storage):
    user = _user()
    batch = await _create(db_session, user)
    storage[1].validate_image.side_effect = MalwareScannerUnavailableError("synthetic unavailable")
    with pytest.raises(HTTPException) as error:
        await routes.upload_ecr_items(
            batch.batch_id, user, db_session, [_file()], json.dumps([str(uuid.uuid4())])
        )
    assert error.value.status_code == 503
    assert error.value.detail == "Image security scanning is unavailable; retry this upload"
    assert list((await db_session.scalars(select(EcrItemModel))).all()) == []
    storage[0].upload_file.assert_not_awaited()
    storage[0].delete_files.assert_not_awaited()


@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_storage_failure_cleans_only_its_attempt_key_before_database_acceptance(db_session, storage, cleanup_fails):
    user = _user()
    batch = await _create(db_session, user)
    storage[0].upload_file.side_effect = RuntimeError("synthetic storage unavailable")
    if cleanup_fails:
        storage[0].delete_files.side_effect = RuntimeError("synthetic cleanup unavailable")
    with pytest.raises(RuntimeError, match="synthetic storage unavailable"):
        await routes.upload_ecr_items(
            batch.batch_id, user, db_session, [_file()], json.dumps([str(uuid.uuid4())])
        )
    key = storage[0].upload_file.await_args.args[1]
    assert key.startswith(f"ecr-checks/{user.agency_id}/{batch.batch_id}/")
    storage[0].delete_files.assert_awaited_once_with([key])
    assert list((await db_session.scalars(select(EcrItemModel))).all()) == []


@pytest.mark.parametrize("started", [False, True])
async def test_new_upload_after_full_or_started_batch_is_rejected_before_scanning(db_session, storage, started):
    user = _user()
    batch = await _create(db_session, user)
    await routes.upload_ecr_items(
        batch.batch_id, user, db_session, [_file()], json.dumps([str(uuid.uuid4())]),
    )
    if started:
        await routes.start_ecr_batch(batch.batch_id, user, db_session)
    with pytest.raises(HTTPException) as error:
        await routes.upload_ecr_items(
            batch.batch_id, user, db_session, [_file()], json.dumps([str(uuid.uuid4())]),
        )
    assert error.value.status_code == 409
    assert len(list((await db_session.scalars(select(EcrItemModel))).all())) == 1
    storage[1].validate_image.assert_awaited_once()
    storage[0].upload_file.assert_awaited_once()


async def test_empty_upload_request_does_not_scan_or_store(db_session, storage):
    user = _user()
    batch = await _create(db_session, user)
    with pytest.raises(HTTPException) as error:
        await routes.upload_ecr_items(batch.batch_id, user, db_session, [], "[]")
    assert error.value.status_code == 422
    storage[1].validate_image.assert_not_awaited()
    storage[0].upload_file.assert_not_awaited()


async def test_unsupported_declared_image_format_keeps_an_explicit_failed_row(db_session, storage):
    user = _user()
    batch = await _create(db_session, user)
    file = _file()
    file.headers = Headers({"content-type": "image/tiff"})
    result = await routes.upload_ecr_items(
        batch.batch_id, user, db_session, [file], json.dumps([str(uuid.uuid4())]),
    )
    assert result.failed_count == 1 and result.items[0].reason == "invalid_image_upload"
    storage[1].validate_image.assert_not_awaited()
    storage[0].upload_file.assert_not_awaited()


async def test_late_conflicting_filename_preserves_winner_and_cleans_losing_attempt(db_session, storage):
    user = _user()
    batch = await _create(db_session, user)
    client_id, winner_id = uuid.uuid4(), uuid.uuid4()
    winner_key = f"ecr-checks/{user.agency_id}/{batch.batch_id}/{winner_id}.jpg"

    async def concurrent_commit(content, key, content_type):
        assert key != winner_key
        db_session.add(EcrItemModel(
            id=winner_id, batch_id=batch.batch_id, client_id=client_id,
            original_filename="other.jpg", content_type="image/jpeg", object_key=winner_key,
            sha256=hashlib.sha256(_image()).hexdigest(),
        ))
        await db_session.commit()

    storage[0].upload_file.side_effect = concurrent_commit
    with pytest.raises(HTTPException) as error:
        await routes.upload_ecr_items(
            batch.batch_id, user, db_session, [_file()], json.dumps([str(client_id)]),
        )
    assert error.value.status_code == 409
    rows = list((await db_session.scalars(select(EcrItemModel))).all())
    assert len(rows) == 1 and rows[0].id == winner_id and rows[0].object_key == winner_key
    losing_key = storage[0].upload_file.await_args.args[1]
    storage[0].delete_files.assert_awaited_once_with([losing_key])
    assert losing_key != winner_key


@pytest.mark.parametrize("fails", [False, True])
async def test_real_dispatch_uses_the_durable_job_even_when_broker_is_unavailable(monkeypatch, fails):
    from app.infrastructure import ecr

    batch_id = uuid.uuid4()
    dispatch = AsyncMock(side_effect=RuntimeError("synthetic broker unavailable") if fails else None)
    monkeypatch.setattr(ecr, "dispatch_ecr_batch", dispatch)
    await _real_dispatch(batch_id)
    dispatch.assert_awaited_once_with(batch_id)


async def test_retry_rejects_an_unfinished_batch(db_session, storage):
    user = _user()
    batch = await _create(db_session, user)
    with pytest.raises(HTTPException) as error:
        await routes.retry_ecr_batch(batch.batch_id, user, db_session)
    assert error.value.status_code == 409
    routes._dispatch.assert_not_awaited()


async def test_retry_does_not_requeue_an_invalid_image_without_storage(db_session, storage):
    user = _user()
    batch = await _create(db_session, user)
    file = _file()
    file.headers = Headers({"content-type": "image/tiff"})
    await routes.upload_ecr_items(
        batch.batch_id, user, db_session, [file], json.dumps([str(uuid.uuid4())]),
    )
    from app.infrastructure.database.ecr_models import EcrBatchModel

    saved = await db_session.get(EcrBatchModel, batch.batch_id)
    saved.status = "completed_with_errors"
    await db_session.commit()
    with pytest.raises(HTTPException) as error:
        await routes.retry_ecr_batch(batch.batch_id, user, db_session)
    assert error.value.status_code == 409
    item = (await db_session.scalars(select(EcrItemModel))).one()
    assert item.status == "failed" and item.object_key is None
    routes._dispatch.assert_not_awaited()


async def test_cancelled_admission_settles_a_late_failure_and_releases_the_slot():
    started, release = asyncio.Event(), asyncio.Event()

    async def operation():
        started.set()
        await release.wait()
        raise RuntimeError("synthetic late failure")

    task = asyncio.create_task(routes._run_admitted_upload(operation))
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        next_operation = AsyncMock(return_value="next")
        assert await asyncio.wait_for(routes._run_admitted_upload(next_operation), timeout=2) == "next"
        next_operation.assert_awaited_once_with()
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)


async def test_oversize_valid_image_closes_every_file_before_scanning(db_session, storage, monkeypatch):
    user = _user()
    batch = await _create(db_session, user, 2)
    files = [_file(), _file()]
    monkeypatch.setattr(uploads, "get_settings", lambda: SimpleNamespace(ecr_image_max_bytes=len(_image()) - 1))
    with pytest.raises(HTTPException) as error:
        await routes.upload_ecr_items(
            batch.batch_id, user, db_session, files,
            json.dumps([str(uuid.uuid4()), str(uuid.uuid4())]),
        )
    assert error.value.status_code == 413
    assert all(file.file.closed for file in files)
    storage[1].validate_image.assert_not_awaited()
    storage[0].upload_file.assert_not_awaited()
    assert list((await db_session.scalars(select(EcrItemModel))).all()) == []
