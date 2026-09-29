"""Bounded reads and native cancellation drainage without external object storage."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from app.domain.exceptions.exceptions import StorageError
from app.infrastructure.storage import mcp_image_export_storage as module
from app.infrastructure.storage.mcp_image_export_storage import MCPImageExportStorage
from tests.integration.test_mcp_image_exports import Images


async def test_unknown_key_is_rejected_before_any_storage_request():
    adapter = MCPImageExportStorage(object(), ["known"])
    with pytest.raises(StorageError, match="outside"):
        await adapter.get_file("other")


async def test_actual_size_checksum_and_total_reservations_are_bounded(monkeypatch):
    storage = Images()
    storage.retain("one", "red")
    size = len(storage.objects["one"][0])
    adapter = MCPImageExportStorage(storage, ["one"], maximum_source_bytes=size - 1)
    with pytest.raises(StorageError, match="size"):
        await adapter.get_file("one")
    assert not storage.read_sizes
    monkeypatch.setattr(module, "MAX_IMAGE_ARCHIVE_BYTES", size)
    adapter = MCPImageExportStorage(storage, ["one"])
    await adapter.get_file("one")
    with pytest.raises(StorageError, match="export size"):
        await adapter.get_file("one")
    storage.corrupt = True
    with pytest.raises(StorageError, match="checksum"):
        await MCPImageExportStorage(storage, ["one"]).get_file("one")


async def test_pixel_admission_rejects_large_dimensions_before_decode(monkeypatch):
    from app.infrastructure.imaging import passport_image_cropper

    storage = Images()
    storage.retain("one", "red")
    monkeypatch.setattr(
        passport_image_cropper,
        "get_settings",
        lambda: SimpleNamespace(upload_max_file_size_bytes=1024 * 1024, upload_max_pixels=100),
    )
    with pytest.raises(passport_image_cropper.PassportImageCropError, match="resolution"):
        await MCPImageExportStorage(storage, ["one"]).get_file("one")


async def test_cancelled_native_inspection_finishes_before_reader_returns(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    finished = []

    def inspect(_content):
        entered.set()
        assert release.wait(5)
        finished.append(True)

    monkeypatch.setattr(module, "inspect_passport_image", inspect)
    storage = Images()
    storage.retain("one", "red")
    task = asyncio.create_task(MCPImageExportStorage(storage, ["one"]).get_file("one"))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0.02)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished == [True]
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
