"""Sibling image mutations wait for native writes before compensating."""

from __future__ import annotations

import asyncio
import threading

import pytest

from tests.passport_image_mutations import (
    configure_image_mutation_adapters,
    invoke_image_mutation,
    seed_image_mutation_context,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["crop", "generate", "select-ai", "apply-ai"])
@pytest.mark.parametrize("cancel", [False, True], ids=["ordinary", "cancel"])
async def test_native_image_mutation_write_lifetime(db_session, monkeypatch, operation, cancel):
    context = await seed_image_mutation_context(db_session)
    configure_image_mutation_adapters(monkeypatch, context)
    existing = set(context.storage.objects)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def write(content, key):
        entered.set()
        if not release.wait(5):
            raise TimeoutError("Synthetic image writer was not released")
        context.storage.objects[key] = content
        finished.set()
        return key

    async def upload(content, key, _content_type):
        return await asyncio.to_thread(write, content, key)

    context.storage.upload_file = upload
    task = asyncio.create_task(invoke_image_mutation(operation, context, db_session))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        if cancel:
            task.cancel()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            abandoned = task.done()
        release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task
        assert await asyncio.to_thread(finished.wait, 3)
        if cancel:
            assert not abandoned, "The image request released a native write before it finished"
            assert set(context.storage.objects) == existing, "Cancelled writes left private objects"
        else:
            assert set(context.storage.objects) > existing
    finally:
        release.set()
        if not task.done():
            await asyncio.gather(task, return_exceptions=True)
