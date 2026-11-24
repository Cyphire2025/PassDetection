"""Actual signed sink iterator with synthetic bytes and botocore streaming bodies."""

from __future__ import annotations

import asyncio
import io
import threading
from contextvars import ContextVar

import pytest
from botocore.response import StreamingBody
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.infrastructure.audit.s3_checkpoint_sink import S3AuditIntegritySink
from tests.unit.infrastructure.test_audit_checkpoints import Store, checkpoint

CONTEXT = ContextVar("synthetic_checkpoint_context", default="missing")


class NativeRead:
    def __init__(self, *, block_at=None, failure_at=None, cleanup_fails=False):
        self.block_at, self.failure_at = block_at, failure_at
        self.cleanup_fails = cleanup_fails
        self.started, self.release = threading.Event(), threading.Event()
        self.error = OSError("synthetic native failure")
        self.close_error = OSError("synthetic close failure")
        self.bodies = []
        self.phases = []
        self.contexts = []

    def phase(self, name):
        self.phases.append(name)
        self.contexts.append(CONTEXT.get())
        if name == self.block_at:
            self.started.set()
            if not self.release.wait(3):
                raise TimeoutError("synthetic native gate")
        if name == self.failure_at:
            raise self.error

    def get(self, store, **options):
        self.phase("get")
        response = store.objects[options["Key"]]
        body = Body(self, response["Body"])
        self.bodies.append(body)
        return {**response, "Body": body}


class Body(StreamingBody):
    def __init__(self, native, raw):
        super().__init__(io.BytesIO(raw), len(raw))
        self.native, self.close_count = native, 0

    def read(self, amount=None):
        self.native.phase("read")
        return super().read(amount)

    def close(self):
        self.close_count += 1
        self.native.phase("close")
        super().close()
        if self.native.cleanup_fails:
            raise self.native.close_error


async def fixture(native):
    key = Ed25519PrivateKey.generate()
    store = Store()
    sink = S3AuditIntegritySink(
        store, "synthetic-checkpoint-only", public_keys=[key.public_key()], private_key=key
    )
    anchor = checkpoint()
    await sink.publish(anchor)
    store.get_object = lambda **options: native.get(store, **options)
    return sink, anchor


async def consume(sink):
    return [item async for item in sink.checkpoints()]


@pytest.mark.parametrize("phase", ["get", "read", "close"])
@pytest.mark.parametrize("cancels", [1, 3])
async def test_cancellation_drains_native_phase_and_closes_body_once(phase, cancels):
    native = NativeRead(block_at=phase)
    sink, _ = await fixture(native)
    token = CONTEXT.set("initiating-operator")
    task = asyncio.create_task(consume(sink))
    try:
        assert await asyncio.to_thread(native.started.wait, 3)
        for number in range(cancels):
            task.cancel("first cancellation" if number == 0 else "later cancellation")
            await asyncio.sleep(0)
        assert not task.done(), "owner must retain its native operation until cleanup finishes"
        native.release.set()
        with pytest.raises(asyncio.CancelledError, match="first cancellation"):
            await task
        assert len(native.bodies) == 1
        assert native.bodies[0]._raw_stream.closed
        assert native.bodies[0].close_count == 1
        assert native.phases[-1] == "close"
        assert native.contexts == ["initiating-operator"] * len(native.contexts)
        if phase == "get":
            assert "read" not in native.phases
    finally:
        native.release.set()
        await asyncio.gather(task, return_exceptions=True)
        for body in native.bodies:
            body._raw_stream.close()
        CONTEXT.reset(token)


@pytest.mark.parametrize("fault", ["get", "read", "close"])
async def test_ordinary_native_error_identity_and_cleanup_order_are_preserved(fault):
    native = NativeRead(failure_at=fault)
    sink, _ = await fixture(native)
    try:
        with pytest.raises(OSError) as raised:
            await consume(sink)
        assert raised.value is native.error
        assert native.phases == (["get"] if fault == "get" else ["get", "read", "close"])
        assert [body.close_count for body in native.bodies] == ([] if fault == "get" else [1])
    finally:
        for body in native.bodies:
            body._raw_stream.close()


@pytest.mark.parametrize("fault", ["late_native_error", "close_error"])
async def test_cancellation_outcome_survives_late_native_and_cleanup_errors(fault):
    native = NativeRead(
        block_at="get",
        failure_at="get" if fault == "late_native_error" else None,
        cleanup_fails=fault == "close_error",
    )
    sink, _ = await fixture(native)
    task = asyncio.create_task(consume(sink))
    try:
        assert await asyncio.to_thread(native.started.wait, 3)
        task.cancel("initiating cancellation")
        await asyncio.sleep(0)
        task.cancel("repeated cancellation")
        await asyncio.sleep(0)
        assert not task.done()
        native.release.set()
        with pytest.raises(asyncio.CancelledError, match="initiating cancellation"):
            await task
        assert [body.close_count for body in native.bodies] == (
            [] if fault == "late_native_error" else [1]
        )
        assert all(body._raw_stream.closed for body in native.bodies)
    finally:
        native.release.set()
        await asyncio.gather(task, return_exceptions=True)
        for body in native.bodies:
            body._raw_stream.close()


async def test_healthy_context_and_signed_checkpoint_are_unchanged():
    native = NativeRead()
    sink, original = await fixture(native)
    token = CONTEXT.set("healthy-operator")
    try:
        assert await consume(sink) == [original]
        assert native.contexts == ["healthy-operator"] * 3
        assert native.phases == ["get", "read", "close"]
        assert native.bodies[0]._raw_stream.closed
        assert native.bodies[0].close_count == 1
    finally:
        CONTEXT.reset(token)


def test_asyncio_runner_shutdown_drains_pending_response_ownership():
    native = NativeRead(block_at="get")
    timer = threading.Timer(0.05, native.release.set)

    async def leave_pending_owner():
        sink, _ = await fixture(native)
        task = asyncio.create_task(consume(sink))
        assert await asyncio.to_thread(native.started.wait, 3)
        timer.start()
        return task  # Runner's real shutdown sweep cancels this pending owner.

    try:
        owner = asyncio.run(leave_pending_owner())
        assert owner.cancelled()
        assert len(native.bodies) == 1
        assert native.bodies[0]._raw_stream.closed
        assert native.bodies[0].close_count == 1
        assert native.phases == ["get", "close"]
    finally:
        native.release.set()
        if timer.ident is not None:
            timer.join(1)
        for body in native.bodies:
            body._raw_stream.close()
