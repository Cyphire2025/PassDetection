"""Upload cleanup distinguishes failed flushes from uncertain commit outcomes."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.presentation.api.v1.document_chunk_uploads import DocumentChunkMetadata
from app.presentation.api.v1.routes import document_distribution_upload_commit as owner


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [None, "flush", "flush-cancel", "commit", "commit-cancel"])
async def test_chunk_commit_preserves_or_compensates_storage_at_the_correct_boundary(
    monkeypatch, failure
):
    events = []
    session = MagicMock()

    async def flush():
        events.append("flush")
        if failure == "flush":
            raise RuntimeError("synthetic flush failure")
        if failure == "flush-cancel":
            raise asyncio.CancelledError

    async def commit():
        events.append("commit")
        if failure == "commit":
            raise RuntimeError("synthetic uncertain commit")
        if failure == "commit-cancel":
            raise asyncio.CancelledError

    async def rollback():
        events.append("rollback")

    async def compensate(*_args, **_kwargs):
        events.append("compensate")

    async def eager_cleanup():
        events.append("eager-cleanup")

    session.flush = AsyncMock(side_effect=flush)
    session.commit = AsyncMock(side_effect=commit)
    session.rollback = AsyncMock(side_effect=rollback)
    cleanup = AsyncMock(side_effect=compensate)
    staging_cleanup = AsyncMock(side_effect=eager_cleanup)
    monkeypatch.setattr(owner, "_cleanup_distribution_storage_keys", cleanup)
    monkeypatch.setattr(owner, "_cleanup_remembered_request_staging", staging_cleanup)
    metadata = DocumentChunkMetadata(uuid.uuid4(), uuid.uuid4(), 0, 1, 1)
    agency_id, group_id = uuid.uuid4(), uuid.uuid4()
    ingestion = SimpleNamespace(
        batch=SimpleNamespace(status="processing"),
        rejected=[],
        created_storage_keys=("document-distribution/synthetic.pdf",),
    )

    async def execute():
        await owner.commit_distribution_upload(
            session=session,
            ingestion=ingestion,
            chunk_metadata=metadata,
            chunk_completes_upload=True,
            agency_id=agency_id,
            group_id=group_id,
            document_type="visa",
            fingerprint="same",
            incoming_file_count=1,
            chunk_byte_count=10,
            replacement_cleanup_ids=[],
        )

    if failure:
        with pytest.raises(asyncio.CancelledError if failure.endswith("cancel") else RuntimeError):
            await execute()
    else:
        await execute()
    receipt = session.add.call_args.args[0]
    assert receipt.id == metadata.chunk_id
    assert receipt.upload_id == metadata.upload_id
    assert receipt.agency_id == agency_id and receipt.group_id == group_id
    assert receipt.file_count == receipt.accepted_count == 1
    assert receipt.rejected_count == 0
    assert ingestion.batch.status == "draft"
    if failure and failure.startswith("flush"):
        assert events == ["flush", "rollback", "compensate"]
        cleanup.assert_awaited_once_with(
            list(ingestion.created_storage_keys),
            agency_id=agency_id,
            group_id=group_id,
            document_type="visa",
        )
        session.commit.assert_not_awaited()
        staging_cleanup.assert_not_awaited()
    elif failure:
        assert events == ["flush", "commit", "rollback"]
        cleanup.assert_not_awaited()
        staging_cleanup.assert_not_awaited()
    else:
        assert events == ["flush", "commit", "eager-cleanup"]
        cleanup.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_commit_defers_failed_replacement_cleanup_and_continues_after_commit(
    monkeypatch,
):
    events = []
    session = MagicMock(flush=AsyncMock(), rollback=AsyncMock())
    session.commit = AsyncMock(side_effect=lambda: events.append("commit"))
    staging = AsyncMock(side_effect=lambda: events.append("staging"))
    first, second = uuid.uuid4(), uuid.uuid4()

    async def replacement_cleanup(cleanup_id):
        events.append(cleanup_id)
        if cleanup_id == first:
            raise RuntimeError("synthetic deferred cleanup")

    cleanup = AsyncMock(side_effect=replacement_cleanup)
    monkeypatch.setattr(owner, "_cleanup_remembered_request_staging", staging)
    monkeypatch.setattr(owner, "process_storage_cleanup_job", cleanup)
    await owner.commit_distribution_upload(
        session=session,
        ingestion=SimpleNamespace(),
        chunk_metadata=None,
        chunk_completes_upload=True,
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        document_type="visa",
        fingerprint=None,
        incoming_file_count=1,
        chunk_byte_count=10,
        replacement_cleanup_ids=[first, second],
    )
    assert events == ["commit", "staging", first, second]
    session.flush.assert_not_awaited()
    session.add.assert_not_called()
    session.rollback.assert_not_awaited()
