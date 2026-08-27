"""Characterization tests for idempotent passport-deletion replay support."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.presentation.api.v1.routes.passport_deletion_support import (
    previous_bulk_delete_result,
)


@pytest.mark.asyncio
async def test_previous_bulk_delete_result_replays_only_complete_durable_metadata() -> None:
    group_id = uuid.uuid4()
    submission_ids = [uuid.uuid4(), uuid.uuid4()]
    session = AsyncMock(spec=AsyncSession)
    query_result = MagicMock()
    query_result.scalar_one_or_none.return_value = SimpleNamespace(
        metadata_json={"deleted_count": 2, "deleted_notifications": 3}
    )
    session.execute.return_value = query_result

    replay = await previous_bulk_delete_result(
        session,
        group_id=group_id,
        request_fingerprint="sha256:test-request",
        requested_submission_ids=submission_ids,
    )

    assert replay is not None
    assert replay.deleted_count == 2
    assert replay.deleted_submission_ids == submission_ids
    assert replay.deleted_notifications == 3
    assert replay.deleted_storage_objects == 0
    assert replay.storage_cleanup_deferred is True

    query_result.scalar_one_or_none.return_value = SimpleNamespace(
        metadata_json={"deleted_count": "2", "deleted_notifications": 3}
    )
    assert (
        await previous_bulk_delete_result(
            session,
            group_id=group_id,
            request_fingerprint="sha256:test-request",
            requested_submission_ids=submission_ids,
        )
        is None
    )
