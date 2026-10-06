"""Real worker-process exclusion, task ownership and cancellation drain."""

from __future__ import annotations

import asyncio
import multiprocessing
import os
import tempfile
import threading
from pathlib import Path

import pytest

from app.core import mcp_export_admission as admission
from app.core import native_image_admission
from app.infrastructure.documents.storage_transfers import run_bounded_storage_operations


def _holder(path, entered):
    async def run():
        with admission.export_slot(directory=Path(path)):
            entered.set()
            await asyncio.Event().wait()

    asyncio.run(run())


def _contender(path, results):
    async def run():
        try:
            with admission.export_slot(directory=Path(path)):
                return "entered"
        except admission.ExportAdmissionBusy:
            return "busy"

    results.put(asyncio.run(run()))


def test_four_processes_share_one_nonwaiting_slot_and_crash_releases_it(tmp_path):
    context = multiprocessing.get_context("spawn")
    entered, results = context.Event(), context.Queue()
    holder = context.Process(target=_holder, args=(str(tmp_path), entered))
    contenders = []
    holder.start()
    try:
        assert entered.wait(15)
        for _ in range(3):
            child = context.Process(target=_contender, args=(str(tmp_path), results))
            child.start()
            contenders.append(child)
        assert [results.get(timeout=15) for _ in contenders] == ["busy"] * 3
        for child in contenders:
            child.join(10)
            assert child.exitcode == 0
        holder.terminate()
        holder.join(10)
        _contender(str(tmp_path), results)
        assert results.get(timeout=5) == "entered"
    finally:
        for process in [holder, *contenders]:
            if process.is_alive():
                process.terminate()
            process.join(5)
        results.close()


async def _try_entry(directory):
    try:
        with admission.export_slot(directory=directory):
            return "entered"
    except admission.ExportAdmissionBusy:
        return "busy"


async def test_default_test_slot_is_private_but_preserves_real_task_exclusion(tmp_path):
    directory = tmp_path / "passdetection-mcp-exports-v1"
    assert Path(tempfile.gettempdir()) != tmp_path

    async def default_entry():
        try:
            with admission.export_slot():
                return "entered"
        except admission.ExportAdmissionBusy:
            return "busy"

    with admission.export_slot():
        assert (directory / "execute.lock").is_file()
        # Imported aliases and the application decorator use this same real
        # kernel lease, while unrelated xdist workers have their own directory.
        assert await asyncio.create_task(default_entry()) == "busy"
        assert await asyncio.create_task(_try_entry(directory)) == "busy"
        with admission.export_slot():
            pass
    assert await asyncio.create_task(default_entry()) == "entered"


async def test_same_task_reentry_never_authorizes_an_inherited_child_task(tmp_path):
    with admission.export_slot(directory=tmp_path):
        with admission.export_slot(directory=tmp_path):
            assert await asyncio.create_task(_try_entry(tmp_path)) == "busy"
    assert await asyncio.create_task(_try_entry(tmp_path)) == "entered"


async def test_native_failure_releases_slot_and_preserves_exception(tmp_path):
    with pytest.raises(ValueError, match="source failed"):
        with admission.export_slot(directory=tmp_path):
            raise ValueError("source failed")
    assert await _try_entry(tmp_path) == "entered"


@pytest.mark.parametrize("helper", ["_open_lock", "_try_lock"])
async def test_lock_failure_is_closed_and_does_not_leak_descriptors(tmp_path, monkeypatch, helper):
    before = set(native_image_admission._open_descriptors)

    def failed(*args):
        raise OSError("private/path/must/not/escape")

    monkeypatch.setattr(admission, helper, failed)
    with pytest.raises(admission.ExportAdmissionBusy) as error:
        with admission.export_slot(directory=tmp_path):
            pytest.fail("Lock failure bypassed admission")
    assert "private" not in str(error.value)
    assert native_image_admission._open_descriptors == before


async def test_repeated_cancellation_holds_lease_until_native_worker_exits(tmp_path):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def native():
        try:
            entered.set()
            assert release.wait(10)
        finally:
            finished.set()

    async def export():
        with admission.export_slot(directory=tmp_path):
            await run_bounded_storage_operations([lambda: asyncio.to_thread(native)])

    task = asyncio.create_task(export())
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert await _try_entry(tmp_path) == "busy"
            assert not finished.is_set()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert finished.is_set()
    assert await _try_entry(tmp_path) == "entered"


def _forked_child(entered, release):
    entered.set()
    release.wait(10)


@pytest.mark.skipif(os.name != "posix", reason="Linux fork descriptor inheritance")
async def test_parser_fork_cannot_retain_parent_export_lease(tmp_path):
    context = multiprocessing.get_context("fork")
    entered, release = context.Event(), context.Event()
    child = context.Process(target=_forked_child, args=(entered, release))
    try:
        with admission.export_slot(directory=tmp_path):
            child.start()
            assert entered.wait(3)
        assert child.is_alive()
        assert await asyncio.create_task(_try_entry(tmp_path)) == "entered"
    finally:
        release.set()
        child.join(5)
        if child.is_alive():
            child.terminate()
            child.join(5)
