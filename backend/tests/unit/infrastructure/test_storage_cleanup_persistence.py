"""Encrypted cleanup stays durable and bounded across real SQLite transactions."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infrastructure.database.models import AuditLogModel, StorageCleanupJobModel
from app.infrastructure.database.traveller_reuse_models import TravellerDocumentAssetModel
from app.infrastructure.documents.storage_cleanup import (
    StorageCleanupCipher,
    process_due_storage_cleanup_jobs,
    process_storage_cleanup_job,
    stage_storage_cleanup_job,
)
from tests.unit.application.test_traveller_snapshot_access import snapshot


def stage(session, keys, *, source="document_distribution_delete", agency_id=None):
    cipher = StorageCleanupCipher("synthetic-cleanup-secret-123456")
    job = stage_storage_cleanup_job(
        session,
        agency_id=agency_id,
        source=source,
        context_id=uuid.uuid4().hex,
        storage_keys=keys,
        cipher=cipher,
    )
    assert job is not None
    return job, cipher


@pytest.mark.asyncio
async def test_due_batch_keeps_limit_and_replaces_only_completed_rows_with_audit(db_session):
    jobs = [stage(db_session, [f"document-distribution/group/{index}.pdf"])[0]
            for index in range(3)]
    job_ids = {job.id for job in jobs}
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    storage = SimpleNamespace(delete_files=AsyncMock(return_value=1))
    cipher = StorageCleanupCipher("synthetic-cleanup-secret-123456")

    assert await process_due_storage_cleanup_jobs(
        limit=2, session_factory=factory, storage_factory=lambda: storage, cipher=cipher
    ) == 2
    db_session.expire_all()
    remaining = list(await db_session.scalars(select(StorageCleanupJobModel)))
    audits = list(await db_session.scalars(select(AuditLogModel)))
    assert len(remaining) == 1 and remaining[0].id in job_ids
    assert remaining[0].status == "pending" and remaining[0].attempts == 0
    assert len(audits) == 2 and storage.delete_files.await_count == 2
    assert all(row.action == "document_storage_cleanup_completed" for row in audits)
    assert "document-distribution/" not in repr([row.metadata_json for row in audits])


@pytest.mark.asyncio
async def test_retained_trip_object_is_kept_while_unreferenced_peer_is_deleted(db_session):
    _, _, asset, group, _, _ = await snapshot(db_session)
    asset_id = asset.id
    held_key, unused_key = asset.object_key, "travellers/unreferenced/synthetic.jpg"
    job, cipher = stage(db_session, [held_key, unused_key],
                        source="traveller_copy_revoked", agency_id=group.agency_id)
    job_id = job.id
    await db_session.commit()
    storage = SimpleNamespace(delete_files=AsyncMock(side_effect=lambda keys: len(keys)))
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    result = await process_storage_cleanup_job(
        job_id, session_factory=factory, storage_factory=lambda: storage, cipher=cipher
    )
    assert result is not None and result.completed
    assert result.object_count == 2 and result.deleted_count == 1
    storage.delete_files.assert_awaited_once_with([unused_key])
    db_session.expire_all()
    assert await db_session.get(StorageCleanupJobModel, job_id) is None
    retained = await db_session.get(TravellerDocumentAssetModel, asset_id)
    assert retained is not None and retained.object_key == held_key


@pytest.mark.asyncio
@pytest.mark.parametrize("unreadable", [False, True])
async def test_incomplete_or_unreadable_claim_stays_durable_without_busy_retry(
    db_session, unreadable
):
    job, cipher = stage(db_session, ["document-distribution/group/synthetic.pdf"])
    job_id = job.id
    ciphertext = bytes(job.storage_keys_ciphertext)
    await db_session.commit()
    storage = SimpleNamespace(delete_files=AsyncMock(return_value=0))
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    if unreadable:
        cipher = StorageCleanupCipher("synthetic-other-secret-654321")

    result = await process_storage_cleanup_job(
        job_id, session_factory=factory, storage_factory=lambda: storage, cipher=cipher
    )
    assert result is not None and not result.completed
    db_session.expire_all()
    persisted = await db_session.get(StorageCleanupJobModel, job_id)
    assert persisted is not None and persisted.attempts == 1
    assert persisted.status == ("blocked" if unreadable else "pending")
    assert bytes(persisted.storage_keys_ciphertext) == ciphertext
    assert await process_storage_cleanup_job(
        job_id, session_factory=factory, storage_factory=lambda: storage, cipher=cipher
    ) is None
    assert storage.delete_files.await_count == (0 if unreadable else 1)
