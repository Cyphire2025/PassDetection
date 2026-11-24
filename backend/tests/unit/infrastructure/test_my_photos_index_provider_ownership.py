"""A bounded indexing batch owns every started native SDK sibling."""

import asyncio
import threading

import pytest

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import FaceIndexAsset, FaceIndexBatchRequest
from app.infrastructure.my_photos.aws_client_runtime import _async_client_call
from app.infrastructure.my_photos.aws_providers import (
    AwsRekognitionFaceIndexSearchProvider,
    aws_provider_config,
)
from tests.unit.infrastructure.test_my_photos_aws_providers import GROUP_ID, TENANT_ID, _settings


@pytest.mark.parametrize("late_failure", [False, True])
async def test_index_batch_failure_drains_native_sibling(monkeypatch, late_failure):
    provider = AwsRekognitionFaceIndexSearchProvider(
        rekognition_client=object(),
        liveness_provider=object(),
        config=aws_provider_config(_settings(aws_index_concurrency=2)),
    )
    started = asyncio.Event()
    release, finished = threading.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    entered = []

    def native():
        loop.call_soon_threadsafe(started.set)
        try:
            if not release.wait(5):
                raise AssertionError("Synthetic index worker was not released")
            if late_failure:
                raise ValueError("Synthetic late indexing failure")
            return (), None
        finally:
            finished.set()

    async def index_one(_request, asset):
        entered.append(asset.asset_identity)
        if asset.asset_identity == "first":
            await started.wait()
            raise MyPhotosUnavailable("SYNTHETIC_FIRST_FAILURE", "Synthetic failure.")
        return await _async_client_call(native)

    monkeypatch.setattr(provider, "_index_one", index_one)
    request = FaceIndexBatchRequest(
        tenant_scope=TENANT_ID,
        group_scope=GROUP_ID,
        collection_reference=provider.collection_reference(
            tenant_scope=TENANT_ID, group_scope=GROUP_ID
        ),
        index_version=1,
        assets=tuple(
            FaceIndexAsset(name, "synthetic-analysis", name) for name in ("first", "second")
        ),
    )
    task = asyncio.create_task(provider.index_faces(request))
    try:
        await asyncio.wait_for(started.wait(), 2)
        for _ in range(10):
            await asyncio.sleep(0)
        assert not task.done(), "Index batch returned while a started native sibling was alive"
        assert not finished.is_set()
    finally:
        release.set()
        outcomes = await asyncio.gather(task, return_exceptions=True)
        assert await asyncio.to_thread(finished.wait, 2)
    assert entered == ["first", "second"]
    assert isinstance(outcomes[0], MyPhotosUnavailable)
    assert outcomes[0].code == "SYNTHETIC_FIRST_FAILURE"
