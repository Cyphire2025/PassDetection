"""A media worker cannot schedule its retry while a native sibling still runs."""

import asyncio
import threading
from types import SimpleNamespace

import pytest

from app.application.my_photos.errors import MyPhotosUnavailable
from app.infrastructure.my_photos import operational_runtime
from app.infrastructure.my_photos.aws_client_runtime import _async_client_call
from tests.integration.my_photos_operational_fixtures import operational_media_scope


@pytest.mark.parametrize("late_failure", [False, True])
async def test_media_failure_drains_owned_native_sibling_before_retry(
    db_session, monkeypatch, late_failure
):
    scope = await operational_media_scope(db_session, monkeypatch, job_type="generate_variants")
    started = asyncio.Event()
    release, finished = threading.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    provider_tasks = []

    def native():
        loop.call_soon_threadsafe(started.set)
        try:
            if not release.wait(5):
                raise AssertionError("Synthetic worker was not released")
            if late_failure:
                raise ValueError("Synthetic late media failure")
            return object()
        finally:
            finished.set()

    class Media:
        async def prepare(self, request):
            provider_tasks.append(asyncio.current_task())
            if request.variant == "thumbnail":
                await started.wait()
                raise MyPhotosUnavailable("SYNTHETIC_FIRST_FAILURE", "Synthetic failure.")
            if request.variant == "preview":
                return await _async_client_call(native)
            await asyncio.Event().wait()

    task = asyncio.create_task(
        operational_runtime.execute_operational_job(
            scope.job_id,
            settings=scope.settings,
            providers=SimpleNamespace(media=Media()),
            lease_owner="synthetic-media-worker",
        )
    )
    try:
        await asyncio.wait_for(started.wait(), 2)
        # Enough loop turns for the sibling error's database retry to finish;
        # the native thread remains deterministically blocked throughout.
        for _ in range(60):
            await asyncio.sleep(0.001)
        assert not task.done(), "Retry completed while an owned native provider sibling was alive"
        assert not finished.is_set()
    finally:
        release.set()
        outcomes = await asyncio.gather(task, return_exceptions=True)
        for provider_task in provider_tasks:
            provider_task.cancel()
        await asyncio.gather(*provider_tasks, return_exceptions=True)
        assert await asyncio.to_thread(finished.wait, 2)
    assert outcomes[0].state == "retrying"
