"""A failed manifest owns every started provider sibling until it has stopped."""

import asyncio
import threading
import uuid
from types import SimpleNamespace

import pytest

from app.application.my_photos.errors import MyPhotosUnavailable
from app.infrastructure.my_photos.aws_client_runtime import _async_client_call
from app.infrastructure.my_photos.gallery_manifest_context import GalleryManifestContext
from app.infrastructure.my_photos.gallery_manifest_providers import _verify_media
from tests.unit.infrastructure.test_my_photos_gallery_ingestion import _asset, _request, _settings


@pytest.mark.parametrize("late_failure", [False, True])
@pytest.mark.parametrize("cancel_during_drain", [False, True])
async def test_manifest_failure_drains_started_sdk_sibling_before_returning(
    late_failure, cancel_during_drain
):
    started = asyncio.Event()
    release, finished = threading.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    availability_calls = []
    first_asset, second_asset = _asset(0), _asset(1)

    def native():
        loop.call_soon_threadsafe(started.set)
        try:
            if not release.wait(5):
                raise AssertionError("Synthetic media worker was never released")
            if late_failure:
                raise ValueError("synthetic late media failure")
            return SimpleNamespace(
                storage_reference="versioned:synthetic",
                source_object_reference=second_asset.archive_reference,
                availability_state="original_available_online",
            )
        finally:
            finished.set()

    class Media:
        async def register(self, request):
            if request.asset_identity == first_asset.immutable_asset_key:
                await started.wait()
                raise MyPhotosUnavailable("SYNTHETIC_FIRST_FAILURE", "Synthetic provider failure")
            return await _async_client_call(native)

        async def availability(self, request):
            availability_calls.append(request)
            raise AssertionError("No new variant call should start after batch failure")

    request = _request(
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        manifest_identity="manifest-fixture",
        target_revision=1,
        assets=(first_asset, second_asset),
        total_asset_count=2,
        batch_index=0,
    )
    ctx = GalleryManifestContext(None, _settings(), SimpleNamespace(media=Media()))
    task = asyncio.create_task(_verify_media(ctx, request))
    try:
        await asyncio.wait_for(started.wait(), 2)
        for _ in range(10):
            await asyncio.sleep(0)
        assert not task.done(), (
            "Manifest returned while a started native provider sibling was alive"
        )
        assert not finished.is_set()
        if cancel_during_drain:
            for _ in range(2):
                task.cancel()
                await asyncio.sleep(0)
                assert not task.done(), "Repeated cancellation abandoned a started provider sibling"
    finally:
        release.set()
        outcomes = await asyncio.gather(task, return_exceptions=True)
        assert await asyncio.to_thread(finished.wait, 2)
    if cancel_during_drain:
        assert isinstance(outcomes[0], asyncio.CancelledError)
    else:
        assert isinstance(outcomes[0], MyPhotosUnavailable)
        assert outcomes[0].code == "SYNTHETIC_FIRST_FAILURE"
    assert not availability_calls
