from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.register_my_photos_manifest import _register_requests


@pytest.mark.asyncio
async def test_register_orchestrates_fifty_batches_after_one_shared_step_up() -> None:
    service = SimpleNamespace(register_batch=AsyncMock())
    service.register_batch.side_effect = [
        SimpleNamespace(
            received_asset_count=(index + 1) * 100,
            total_asset_count=5_000,
            state="queued" if index == 49 else "receiving",
            content_fingerprint="f" * 64 if index == 49 else None,
        )
        for index in range(50)
    ]
    requests = tuple(SimpleNamespace(batch_index=index) for index in range(50))
    actor = object()
    verified_at = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    dispatched: list[uuid.UUID] = []
    checkpoints: list[dict[str, object]] = []

    results = await _register_requests(
        service,
        actor=actor,
        mfa_verified_at=verified_at,
        requests=requests,
        dispatch=dispatched.append,
        progress=checkpoints.append,
    )

    assert len(results) == 50
    assert [
        call.kwargs["request"].batch_index for call in service.register_batch.await_args_list
    ] == list(range(50))
    assert all(
        call.kwargs["actor"] is actor and call.kwargs["mfa_verified_at"] is verified_at
        for call in service.register_batch.await_args_list
    )
    assert checkpoints[-1] == {
        "batch_index": 49,
        "received_asset_count": 5_000,
        "total_asset_count": 5_000,
        "state": "queued",
        "checkpoint": "f" * 64,
    }
