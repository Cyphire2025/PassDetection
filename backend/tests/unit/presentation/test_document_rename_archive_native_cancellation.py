"""Archive ownership outlives cancelled requests until actual native IO stops."""

import asyncio
import io
import threading
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.entities.entities import UserRole
from app.presentation.api.v1.routes import document_rename


@pytest.mark.parametrize("cancel_twice", [False, True])
async def test_cancelled_zip_write_drains_before_closing_spool_or_releasing_admission(
    monkeypatch, cancel_twice
):
    loop = asyncio.get_running_loop()
    entered, completed = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    admission = threading.BoundedSemaphore(1)

    class Spool(io.BytesIO):
        def write(self, data):
            if not bytes(data).startswith(b"%PDF"):
                return super().write(data)
            loop.call_soon_threadsafe(entered.set)
            try:
                if not release.wait(5):
                    raise RuntimeError("Synthetic native ZIP write was not released")
                return super().write(data)
            finally:
                loop.call_soon_threadsafe(completed.set)

    spool = Spool()
    batch = SimpleNamespace(id=uuid.uuid4(), status="completed")
    item = SimpleNamespace(
        id=uuid.uuid4(),
        detected_type="visa",
        status="renamed",
        storage_key="synthetic-private-key",
        renamed_filename="SYNTHETIC_VISA.pdf",
    )
    batch_result, items_result = MagicMock(), MagicMock()
    batch_result.scalar_one_or_none.return_value = batch
    items_result.scalars.return_value.all.return_value = [item]
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[batch_result, items_result]), rollback=AsyncMock()
    )
    storage = SimpleNamespace(get_file=AsyncMock(return_value=b"%PDF-1.7\nsynthetic private bytes"))
    monkeypatch.setattr(document_rename, "MinioStorageRepository", lambda: storage)
    monkeypatch.setattr(document_rename, "SpooledTemporaryFile", lambda **_kwargs: spool)
    monkeypatch.setattr(document_rename, "_RENAME_ARCHIVE_ADMISSION", admission)
    user = SimpleNamespace(id=uuid.uuid4(), agency_id=uuid.uuid4(), role=UserRole.AGENCY_ADMIN)
    task = asyncio.create_task(document_rename.download_renamed_zip(batch.id, user, session))
    closed_early = available_early = False
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        await asyncio.wait({task}, timeout=0.05)
        if cancel_twice:
            task.cancel()
            await asyncio.wait({task}, timeout=0.05)
        closed_early = spool.closed
        available_early = admission.acquire(blocking=False)
        if available_early:
            admission.release()
    finally:
        release.set()
        outcomes = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 3)
        await asyncio.wait_for(completed.wait(), 3)
    assert not closed_early, "Spool closed while a real ZipFile native write was still blocked"
    assert not available_early, "Archive admission released before the native worker exited"
    assert isinstance(outcomes[0], asyncio.CancelledError)
    assert spool.closed
    assert admission.acquire(blocking=False)
    admission.release()


async def test_cancelled_stream_read_drains_before_closing_owned_file(monkeypatch):
    loop = asyncio.get_running_loop()
    entered, completed = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    admission = MagicMock()

    class Spool(io.BytesIO):
        def read(self, size=-1):
            loop.call_soon_threadsafe(entered.set)
            try:
                if not release.wait(5):
                    raise RuntimeError("Synthetic native archive read was not released")
                return super().read(size)
            finally:
                loop.call_soon_threadsafe(completed.set)

    spool = Spool(b"synthetic private archive bytes")
    monkeypatch.setattr(document_rename, "_RENAME_ARCHIVE_ADMISSION", admission)
    stream = document_rename._stream_archive(spool, release_admission=True)
    task = asyncio.create_task(anext(stream))
    closed_early = released_early = False
    try:
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        await asyncio.wait({task}, timeout=0.05)
        closed_early = spool.closed
        released_early = admission.release.called
    finally:
        release.set()
        outcomes = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 3)
        await asyncio.wait_for(completed.wait(), 3)
        await stream.aclose()
    assert not closed_early and not released_early
    assert isinstance(outcomes[0], asyncio.CancelledError)
    assert spool.closed
    admission.release.assert_called_once_with()
