"""Keep cleanup failure precedence while shielding the request's owned rollback."""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, Mock

import pytest

from app.presentation.api.v1.routes import document_distribution_compensation as compensation
from app.presentation.api.v1.routes import document_distribution_storage as storage


@pytest.mark.parametrize("fault", ["rollback", "cleanup", "cleanup_cancel"])
async def test_compensation_preserves_cleanup_failure_precedence(monkeypatch, fault):
    root = OSError("synthetic original request failure")
    failure = (
        asyncio.CancelledError("synthetic cleanup cancellation")
        if fault == "cleanup_cancel"
        else RuntimeError("synthetic cleanup failure")
    )
    session = Mock()
    session.rollback = AsyncMock(side_effect=failure if fault == "rollback" else None)
    cleanup = AsyncMock(side_effect=failure)
    monkeypatch.setattr(compensation, "_cleanup_distribution_storage_keys", cleanup)
    with pytest.raises(type(failure)) as raised:
        try:
            raise root
        except OSError:
            await compensation.compensate_uncommitted_document_upload(
                session,
                storage_keys=["synthetic/owned.pdf"],
                agency_id=uuid.uuid4(),
                group_id=uuid.uuid4(),
                document_type="visa",
            )
            raise
    if fault != "cleanup_cancel":
        assert raised.value is failure
    else:
        assert raised.value.args == failure.args
    session.rollback.assert_awaited_once()
    if fault == "rollback":
        cleanup.assert_not_awaited()
    else:
        cleanup.assert_awaited_once()


async def test_empty_owned_keys_do_not_construct_a_storage_client(monkeypatch):
    session = Mock()
    session.rollback = AsyncMock()
    factory = Mock(side_effect=AssertionError("No objects require storage work"))
    monkeypatch.setattr(storage, "MinioStorageRepository", factory)
    await compensation.compensate_uncommitted_document_upload(
        session,
        storage_keys=(),
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        document_type="visa",
    )
    session.rollback.assert_awaited_once()
    factory.assert_not_called()
