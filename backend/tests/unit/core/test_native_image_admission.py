"""Real kernel locks: process/thread contention, crash, cancellation and HTTP boundary."""

from __future__ import annotations

import asyncio
import errno
import multiprocessing
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI

from app.core import native_image_admission as admission
from app.domain.exceptions.resource_capacity import ImageProcessingBusy
from app.presentation.middleware.error_handler import register_exception_handlers


def _process_holder(path, entered, release):
    with admission.native_image_slot(directory=Path(path)):
        entered.set()
        release.wait(15)


def _process_contender(path, results):
    try:
        with admission.native_image_slot(directory=Path(path), wait_seconds=0.05):
            results.put("entered")
    except ImageProcessingBusy:
        results.put("busy")


def test_four_processes_share_one_slot_and_crashed_holder_releases_it(tmp_path):
    context = multiprocessing.get_context("spawn")
    entered, release, results = context.Event(), context.Event(), context.Queue()
    holder = context.Process(target=_process_holder, args=(str(tmp_path), entered, release))
    contenders = []
    holder.start()
    try:
        assert entered.wait(10)
        for _ in range(3):
            child = context.Process(target=_process_contender, args=(str(tmp_path), results))
            child.start()
            contenders.append(child)
        assert [results.get(timeout=10) for _ in contenders] == ["busy"] * 3
        for child in contenders:
            child.join(10)
            assert child.exitcode == 0
        holder.terminate()
        holder.join(10)
        assert not holder.is_alive()
        with admission.native_image_slot(directory=tmp_path, wait_seconds=0.1):
            pass
    finally:
        # A forcibly killed waiter may own multiprocessing.Event's semaphore;
        # never touch that synchronization object after the simulated crash.
        for process in [holder, *contenders]:
            if process.is_alive():
                process.terminate()
            process.join(5)
        results.close()


def test_four_ordinary_operations_complete_without_overlapping_native_pixels(tmp_path):
    barrier, state_lock = threading.Barrier(4), threading.Lock()
    active, peak = 0, 0

    def work():
        nonlocal active, peak
        barrier.wait()
        with admission.native_image_slot(directory=tmp_path, wait_seconds=1):
            with state_lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.03)
            with state_lock:
                active -= 1
        return "complete"

    with ThreadPoolExecutor(max_workers=4) as workers:
        assert list(workers.map(lambda _: work(), range(4))) == ["complete"] * 4
    assert peak == 1


def test_queue_admission_is_bounded_before_any_decode(tmp_path, monkeypatch):
    monkeypatch.setattr(admission, "MAX_ADMITTED_IMAGE_OPERATIONS", 1)
    with admission.native_image_slot(directory=tmp_path):
        with ThreadPoolExecutor(max_workers=1) as workers:
            started = time.monotonic()
            contender = workers.submit(_try_entry, tmp_path)
            assert contender.result(timeout=1) == "busy"
            assert time.monotonic() - started < 0.5


def _try_entry(path):
    try:
        with admission.native_image_slot(directory=path, wait_seconds=0.05):
            return "entered"
    except ImageProcessingBusy:
        return "busy"


def test_nested_same_thread_does_not_release_outer_ownership(tmp_path, monkeypatch):
    monkeypatch.setattr(admission, "_lock_directory", lambda: tmp_path)

    @admission.bounded_native_image
    def inner():
        return "pixels closed"

    @admission.bounded_native_image
    def outer():
        assert inner() == "pixels closed"
        with ThreadPoolExecutor(max_workers=1) as workers:
            assert workers.submit(_try_entry, tmp_path).result(timeout=1) == "busy"
        return "done"

    assert outer() == "done"
    assert _try_entry(tmp_path) == "entered"


@pytest.mark.asyncio
async def test_cancelled_async_caller_cannot_release_running_native_thread(tmp_path, monkeypatch):
    monkeypatch.setattr(admission, "_lock_directory", lambda: tmp_path)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    @admission.bounded_native_image
    def native_work():
        try:
            entered.set()
            assert release.wait(5)
        finally:
            finished.set()

    task = asyncio.create_task(asyncio.to_thread(native_work))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(_try_entry, tmp_path) == "busy"
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 3)
    assert await asyncio.to_thread(_try_entry, tmp_path) == "entered"


def test_setup_failure_is_closed_and_does_not_expose_paths(tmp_path, monkeypatch):
    def inaccessible(*args):
        raise PermissionError("private/path/must/not/escape")

    monkeypatch.setattr(admission, "_open_lock", inaccessible)
    with pytest.raises(ImageProcessingBusy) as error:
        with admission.native_image_slot(directory=tmp_path):
            pytest.fail("Unsafe admission bypass")
    assert "private" not in str(error.value)


def test_lock_failure_closes_candidate_descriptor(tmp_path, monkeypatch):
    def failed(descriptor):
        raise OSError(errno.EIO, "lock service failure")

    monkeypatch.setattr(admission, "_try_lock", failed)
    before = set(admission._open_descriptors)
    with pytest.raises(ImageProcessingBusy):
        with admission.native_image_slot(directory=tmp_path):
            pytest.fail("Lock errors must not bypass admission")
    assert admission._open_descriptors == before


def test_native_failure_releases_slot_and_preserves_original_exception(tmp_path):
    with pytest.raises(ValueError, match="image decode failure"):
        with admission.native_image_slot(directory=tmp_path):
            raise ValueError("image decode failure")
    assert _try_entry(tmp_path) == "entered"


def test_native_heap_is_reclaimed_before_unlock_even_when_operation_fails(tmp_path, monkeypatch):
    calls = []

    def reclaim():
        calls.append("reclaim")
        with ThreadPoolExecutor(max_workers=1) as workers:
            assert workers.submit(_try_entry, tmp_path).result(timeout=1) == "busy"

    monkeypatch.setattr(admission, "_heap_reclaimer", lambda: reclaim)
    with pytest.raises(ValueError, match="invalid image"):
        with admission.native_image_slot(directory=tmp_path):
            raise ValueError("invalid image")
    assert calls == ["reclaim"]


def test_unqualified_linux_allocator_fails_closed_before_native_work(tmp_path, monkeypatch):
    admission._heap_reclaimer.cache_clear()
    monkeypatch.setattr(admission.sys, "platform", "linux")
    monkeypatch.setattr(admission.ctypes, "CDLL", lambda _: SimpleNamespace())
    try:
        with pytest.raises(ImageProcessingBusy):
            with admission.native_image_slot(directory=tmp_path):
                pytest.fail("Unsupported Linux allocator bypassed admission")
    finally:
        admission._heap_reclaimer.cache_clear()


def test_linux_reclaimer_accepts_no_releasable_pages(monkeypatch):
    admission._heap_reclaimer.cache_clear()
    trim = Mock(return_value=0)
    monkeypatch.setattr(admission.sys, "platform", "linux")
    monkeypatch.setattr(admission.ctypes, "CDLL", lambda _: SimpleNamespace(
        gnu_get_libc_version=Mock(), malloc_trim=trim,
    ))
    try:
        admission._heap_reclaimer()()
        trim.assert_called_once_with(0)
    finally:
        admission._heap_reclaimer.cache_clear()


@pytest.mark.skipif(os.name != "posix", reason="Linux kernel path and symlink guard")
def test_symlink_lock_directory_fails_closed(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ImageProcessingBusy):
        with admission.native_image_slot(directory=link):
            pytest.fail("Symlink bypass")


@pytest.mark.asyncio
async def test_capacity_http_response_has_stable_retryable_envelope():
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/native-work")
    async def overloaded():
        raise ImageProcessingBusy()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/native-work")
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"error": {"code": "IMAGE_PROCESSING_BUSY", "message": "Image processing is busy. Please try again shortly."}}


@pytest.mark.parametrize("operation", ["validate", "inspect", "crop", "thumbnail", "visa", "ecr"])
def test_all_pixel_entrypoints_reject_capacity_before_decoding(tmp_path, monkeypatch, operation):
    from PIL import Image

    from app.infrastructure.ai.gemini_ecr_service import prepare_ecr_image
    from app.infrastructure.ai.gemini_visa_image_edit_service import GeminiVisaImageEditService
    from app.infrastructure.imaging.passport_image_cropper import (
        inspect_passport_image,
        render_passport_image_crop,
        render_passport_image_thumbnail,
    )
    from app.infrastructure.security.upload_validator import UploadValidator

    monkeypatch.setattr(admission, "_lock_directory", lambda: tmp_path)
    monkeypatch.setattr(admission, "MAX_ADMITTED_IMAGE_OPERATIONS", 1)
    decode = Mock(side_effect=AssertionError("Pixel decoder must not run while another operation owns admission"))
    monkeypatch.setattr(Image, "open", decode)
    operations = {
        "validate": lambda: UploadValidator(scanner=SimpleNamespace(scan=Mock())).validate(
            content=b"fixture", filename="photo.jpg", declared_content_type="image/jpeg"),
        "inspect": lambda: inspect_passport_image(b"fixture"),
        "crop": lambda: render_passport_image_crop(b"fixture", x=0, y=0, width=1, height=1, rotation_degrees=0),
        "thumbnail": lambda: render_passport_image_thumbnail(b"fixture", max_dimension=240),
        "visa": lambda: GeminiVisaImageEditService._canonical_image(b"fixture"),
        "ecr": lambda: prepare_ecr_image(b"fixture"),
    }
    with admission.native_image_slot(directory=tmp_path):
        with ThreadPoolExecutor(max_workers=1) as workers:
            pending = workers.submit(operations[operation])
            with pytest.raises(ImageProcessingBusy):
                pending.result(timeout=1)
    decode.assert_not_called()


def _forked_idle_child(entered):
    entered.set()
    time.sleep(10)


@pytest.mark.skipif(os.name != "posix", reason="Linux fork descriptor inheritance")
def test_forked_parser_does_not_extend_parent_lock_lifetime(tmp_path):
    context = multiprocessing.get_context("fork")
    entered = context.Event()
    child = context.Process(target=_forked_idle_child, args=(entered,))
    try:
        with admission.native_image_slot(directory=tmp_path):
            child.start()
            assert entered.wait(3)
        assert child.is_alive()
        with ThreadPoolExecutor(max_workers=1) as workers:
            assert workers.submit(_try_entry, tmp_path).result(timeout=1) == "entered"
    finally:
        if child.is_alive():
            child.terminate()
        child.join(5)
