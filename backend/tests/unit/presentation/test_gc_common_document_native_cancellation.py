"""Cancelled GC document staging owns its actual S3 worker until cleanup."""

import asyncio
import hashlib
import io
import threading
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.datastructures import UploadFile
from starlette.requests import Request

from app.infrastructure.storage import minio_repository
from app.presentation.api.v1.routes import gc_app_common_staging as gc_app_content


@pytest.mark.parametrize("cancel_twice", [False, True])
async def test_cancelled_staging_drains_actual_put_before_deleting_owned_key(
    monkeypatch, cancel_twice
):
    loop = asyncio.get_running_loop()
    entered, completed, delete_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    release = threading.Event()
    objects = {}
    payload = b"%PDF-1.7\nsynthetic document"
    deletes = []

    class Client:
        def put_object(self, *, Key, Body, **_kwargs):
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(5):
                raise RuntimeError("Synthetic put was not released")
            objects[Key] = Body
            loop.call_soon_threadsafe(completed.set)
            return {}

        def delete_objects(self, *, Delete, **_kwargs):
            loop.call_soon_threadsafe(delete_started.set)
            for value in Delete["Objects"]:
                key = value["Key"]
                deletes.append(key)
                objects.pop(key, None)
            return {"Errors": []}

    client = Client()
    monkeypatch.setattr(minio_repository, "_shared_s3_clients", lambda: (client, client))

    async def validated(_file):
        return SimpleNamespace(
            content=payload,
            content_type="application/pdf",
            filename="synthetic.pdf",
            sha256_hex=hashlib.sha256(payload).hexdigest(),
        )

    monkeypatch.setattr(gc_app_content, "_validated_common_pdf", validated)
    file = UploadFile(io.BytesIO(payload), filename="synthetic.pdf")
    task = asyncio.create_task(
        gc_app_content._stage_common_document(
            file,
            agency_id=uuid.uuid4(),
            group_id=uuid.uuid4(),
            logical_document_id=uuid.uuid4(),
        )
    )
    deleted_while_writing = False
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        try:
            await asyncio.wait_for(delete_started.wait(), 0.05)
            deleted_while_writing = True
        except TimeoutError:
            pass
        if cancel_twice:
            task.cancel()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        await asyncio.wait_for(completed.wait(), 3)
        await file.close()
    assert not deleted_while_writing, "Compensation ran before the real put_object worker exited"
    assert objects == {}, "Cancelled staging left a private object after early compensation"
    assert len(deletes) == 1


@pytest.mark.parametrize("rollback_error", [asyncio.CancelledError, RuntimeError])
async def test_rollback_failure_still_discards_the_owned_staged_object(monkeypatch, rollback_error):
    access_id, agency_id, group_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    initial = SimpleNamespace(id=access_id, agency_id=agency_id, group_id=group_id, revision=4)
    changed = SimpleNamespace(id=access_id, agency_id=agency_id, group_id=group_id, revision=5)
    group = SimpleNamespace(status="active")
    storage = SimpleNamespace(delete_files=AsyncMock())
    staged = gc_app_content._StagedCommonDocument(
        document_id=uuid.uuid4(),
        logical_document_id=uuid.uuid4(),
        storage_key="gc-app/synthetic/isolated.pdf",
        safe_filename="synthetic.pdf",
        media_type="application/pdf",
        byte_size=16,
        checksum_sha256="a" * 64,
        storage=storage,
    )
    session = MagicMock()
    session.rollback = AsyncMock(
        side_effect=[None, rollback_error("Synthetic rollback interruption")]
    )
    monkeypatch.setattr(
        gc_app_content,
        "_admin_access_context",
        AsyncMock(side_effect=[(initial, group), (changed, group)]),
    )
    monkeypatch.setattr(
        gc_app_content, "require_current_common_document_actor",
        AsyncMock(side_effect=lambda _session, user: user),
    )
    monkeypatch.setattr(gc_app_content, "_stage_common_document", AsyncMock(return_value=staged))
    with pytest.raises(rollback_error):
        await gc_app_content._store_common_document_version(
            session,
            request=Request({"type": "http", "headers": []}),
            current_user=SimpleNamespace(id=uuid.uuid4()),
            group_id=group_id,
            agency_id=agency_id,
            expected_access_revision=4,
            file=MagicMock(),
            category="travel_tips",
            display_name="Synthetic",
            offline_available=True,
        )
    storage.delete_files.assert_awaited_once_with([staged.storage_key])
