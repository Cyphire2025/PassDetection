"""Actual tracker worker ownership across request-task cancellation."""

from __future__ import annotations

import asyncio
import contextlib
import threading
from contextvars import ContextVar

import anyio
import pytest
from sqlalchemy import select

from app.infrastructure.database.models import AuditLogModel
from app.infrastructure.travel_tracker import files as tracker_service
from app.infrastructure.travel_tracker.threading import run_tracker_work
from tests.unit.presentation.test_travel_tracker import tracker as tracker


class _NativeWork:
    def __init__(self, *, failure: bool = False) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.failure = RuntimeError("synthetic late worker error") if failure else None

    def __call__(self, *_args, **_kwargs):
        self.started.set()
        try:
            assert self.release.wait(timeout=2), "test must release its synthetic worker"
            if self.failure is not None:
                raise self.failure
            return b"synthetic workbook"
        finally:
            self.finished.set()

    async def wait_started(self) -> None:
        assert await asyncio.wait_for(asyncio.to_thread(self.started.wait, 1), timeout=2)

    async def finish(self) -> None:
        self.release.set()
        assert await asyncio.wait_for(asyncio.to_thread(self.finished.wait, 1), timeout=2)


@pytest.mark.parametrize("repeated", [False, True])
@pytest.mark.parametrize("late_failure", [False, True])
async def test_asyncio_cancellation_drains_native_work_before_return(repeated, late_failure):
    operation = _NativeWork(failure=late_failure)
    task = asyncio.create_task(run_tracker_work(operation))
    try:
        await operation.wait_started()
        task.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not task.done(), "cancelled request must retain its running native worker"
        if repeated:
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        await operation.finish()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert operation.finished.is_set()
    finally:
        await operation.finish()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_worker_result_keyword_arguments_and_original_failure_are_preserved():
    main_thread = threading.get_ident()

    def operation(value, *, suffix):
        assert threading.get_ident() != main_thread
        return value + suffix

    assert await run_tracker_work(operation, "normal", suffix=" result") == "normal result"
    failure = RuntimeError("synthetic ordinary worker error")

    def failed():
        raise failure

    with pytest.raises(RuntimeError) as caught:
        await run_tracker_work(failed)
    assert caught.value is failure


async def test_normal_tracker_export_retains_worker_until_cancelled_request_drains(
    tracker,
    monkeypatch,
):
    operation = _NativeWork()
    monkeypatch.setattr(tracker_service, "build_export", operation)
    task = asyncio.create_task(tracker.service.export(tracker.group.id))
    try:
        await operation.wait_started()
        task.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not task.done(), "normal authorized export must not abandon its active worker"
        await operation.finish()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not (await tracker.session.scalars(select(AuditLogModel))).all()
    finally:
        await operation.finish()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_cancelled_worker_retains_anyio_thread_capacity_until_it_finishes():
    limiter = anyio.to_thread.current_default_thread_limiter()
    original_limit = limiter.total_tokens
    limiter.total_tokens = 1
    first, second = _NativeWork(), _NativeWork()
    first_task = asyncio.create_task(run_tracker_work(first))
    second_task = None
    try:
        await first.wait_started()
        first_task.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert limiter.borrowed_tokens == 1, "native work must keep its original AnyIO thread token"
        second_task = asyncio.create_task(run_tracker_work(second))
        for _ in range(4):
            await asyncio.sleep(0)
        assert not second.started.is_set(), (
            "a cancelled native worker still occupies its thread slot"
        )
        await first.finish()
        with pytest.raises(asyncio.CancelledError):
            await first_task
        await second.wait_started()
        await second.finish()
        assert await second_task == b"synthetic workbook"
    finally:
        await first.finish()
        if second_task is not None:
            second.release.set()
            await second_task
        with contextlib.suppress(asyncio.CancelledError):
            await first_task
        limiter.total_tokens = original_limit


async def test_anyio_scope_cancellation_waits_for_native_completion_before_exit():
    operation = _NativeWork()
    scopes = []

    async def request():
        with anyio.CancelScope() as scope:
            scopes.append(scope)
            await run_tracker_work(operation)
            await anyio.lowlevel.checkpoint()
        assert operation.finished.is_set()

    task = asyncio.create_task(request())
    try:
        await operation.wait_started()
        scopes[0].cancel()
        await asyncio.sleep(0)
        assert not task.done()
        await operation.finish()
        await task
    finally:
        await operation.finish()
        await task


async def test_worker_receives_request_context_without_mutating_callers_context():
    value = ContextVar("synthetic_tracker_context", default="empty")
    token = value.set("request-context")

    def operation():
        observed = value.get()
        value.set("worker-only")
        return observed

    try:
        assert await run_tracker_work(operation) == "request-context"
        assert value.get() == "request-context"
    finally:
        value.reset(token)


async def test_already_cancelled_anyio_scope_does_not_start_native_work():
    started = threading.Event()
    with anyio.CancelScope() as scope:
        scope.cancel()
        await run_tracker_work(started.set)
    assert not started.is_set()
