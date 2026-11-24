"""Recovery owns native deletions across cancellation, timeouts and failures."""

import asyncio
import threading
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.application.my_photos.errors import MyPhotosUnavailable
from app.application.my_photos.providers import ReferenceDeletionResult
from app.infrastructure.my_photos import recovery_runtime
from app.infrastructure.my_photos.aws_client_runtime import _async_client_call


@pytest.mark.parametrize("exit_kind", ["normal", "cancelled", "timeout", "native_error"])
async def test_deletion_batch_retains_native_children_until_they_stop(monkeypatch, exit_kind):
    entered = [threading.Event(), threading.Event()]
    finish = threading.Event()
    completed = []
    claims = tuple(
        recovery_runtime._DeletionClaim(
            enrollment_id=uuid.uuid4(),
            kind="current",
            agency_id=uuid.uuid4(),
            group_id=uuid.uuid4(),
            passenger_identity_id=uuid.uuid4(),
            provider_reference=str(index),
            deletion_identity=f"synthetic-deletion-{index}",
            attempt_count=1,
        )
        for index in range(2)
    )

    def native_delete(index):
        entered[index].set()
        assert finish.wait(5), "Synthetic native deletion was not released"
        completed.append(index)
        if exit_kind == "native_error":
            raise RuntimeError("synthetic private provider failure")
        return ReferenceDeletionResult("deleted")

    class Provider:
        async def delete_reference(self, request):
            return await _async_client_call(native_delete, int(request.provider_reference))

    settings = SimpleNamespace(
        my_photos=SimpleNamespace(
            provider_deletion_concurrency=2,
            liveness_provider_timeout_seconds=0.02 if exit_kind == "timeout" else 3,
        )
    )
    finalizer = AsyncMock(return_value=recovery_runtime.ProviderDeletionBatchResult(2, 2, 0, 0))
    monkeypatch.setattr(
        recovery_runtime, "_claim_provider_deletions", AsyncMock(return_value=claims)
    )
    monkeypatch.setattr(recovery_runtime, "_finalize_provider_deletions", finalizer)
    task = asyncio.create_task(
        recovery_runtime.execute_provider_deletion_batch(
            settings=settings, providers=SimpleNamespace(liveness=Provider())
        )
    )
    try:
        for signal in entered:
            assert await asyncio.to_thread(signal.wait, 3)
        if exit_kind == "cancelled":
            task.cancel()
            await asyncio.sleep(0.01)
            task.cancel()
        await asyncio.sleep(0.04)
        assert not task.done()
        assert completed == []
        finalizer.assert_not_awaited()
        finish.set()
        if exit_kind == "cancelled":
            with pytest.raises(asyncio.CancelledError):
                await task
            finalizer.assert_not_awaited()
        else:
            await task
            outcomes, resolved = finalizer.call_args.args
            assert resolved is settings
            assert len(outcomes) == 2
            expected = {
                "normal": None,
                "timeout": "PROVIDER_DELETION_TIMEOUT",
                "native_error": "PROVIDER_DELETION_UNAVAILABLE",
            }[exit_kind]
            assert all(outcome.error_code == expected for outcome in outcomes)
            assert all(outcome.complete is (exit_kind == "normal") for outcome in outcomes)
        assert sorted(completed) == [0, 1]
    finally:
        finish.set()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("failure", ["invalid_result", "unavailable"])
async def test_deletion_failure_categories_remain_closed(monkeypatch, failure):
    claim = recovery_runtime._DeletionClaim(
        uuid.uuid4(),
        "current",
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        "synthetic-reference",
        "synthetic-deletion",
        1,
    )

    class Provider:
        async def delete_reference(self, request):
            if failure == "unavailable":
                raise MyPhotosUnavailable("MY_PHOTOS_PROVIDER_UNAVAILABLE", "Synthetic diagnostic.")
            return SimpleNamespace(outcome="unexpected-provider-text")

    settings = SimpleNamespace(
        my_photos=SimpleNamespace(
            provider_deletion_concurrency=1,
            liveness_provider_timeout_seconds=1,
        )
    )
    finalizer = AsyncMock(return_value=recovery_runtime.ProviderDeletionBatchResult(1, 0, 1, 0))
    monkeypatch.setattr(
        recovery_runtime, "_claim_provider_deletions", AsyncMock(return_value=(claim,))
    )
    monkeypatch.setattr(recovery_runtime, "_finalize_provider_deletions", finalizer)
    await recovery_runtime.execute_provider_deletion_batch(
        settings=settings, providers=SimpleNamespace(liveness=Provider())
    )
    (outcome,) = finalizer.call_args.args[0]
    assert outcome.complete is False
    assert outcome.error_code == (
        "PROVIDER_DELETION_RESULT_INVALID"
        if failure == "invalid_result"
        else "MY_PHOTOS_PROVIDER_UNAVAILABLE"
    )
