"""Exercise the actual scheduled scanner with synthetic storage and real owners."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.documents import (
    cleanup_tasks,
    orphan_reconciliation,
    passport_orphan_reconciliation,
)
from app.infrastructure.documents.storage_cleanup import StorageCleanupCipher
from tests.integration.passport_orphan_fixtures import (
    IMAGE_PREFIXES,
    retained_document_keys,
    retained_image_keys,
)
from tests.unit.infrastructure.test_document_orphan_reconciliation import FakeCursor, FakeStorage

NOW = datetime(2026, 10, 31, tzinfo=UTC)
OLD = NOW - timedelta(days=2)


async def reconcile(storage, monkeypatch, session):
    monkeypatch.setattr(
        passport_orphan_reconciliation,
        "AsyncSessionFactory",
        async_sessionmaker(session.bind, expire_on_commit=False),
    )
    # This is the exact async implementation invoked by the existing Celery task.
    return await cleanup_tasks._reconcile_document_storage_orphans(
        storage=storage,
        cursor_client=FakeCursor(),
        cursor_cipher=StorageCleanupCipher("synthetic-passport-orphan-cursor"),
        now=NOW,
    )


@pytest.mark.asyncio
async def test_scheduled_scanner_removes_old_orphans_in_every_private_image_namespace(
    db_session,
    monkeypatch,
):
    storage = FakeStorage({prefix: [(prefix + "orphan.jpg", OLD)] for prefix in IMAGE_PREFIXES})
    result = await reconcile(storage, monkeypatch, db_session)
    assert {key for batch in storage.deleted for key in batch} == {
        prefix + "orphan.jpg" for prefix in IMAGE_PREFIXES
    }
    assert (result.scanned_count, result.stale_candidate_count, result.deleted_count) == (4, 4, 4)


@pytest.mark.asyncio
async def test_all_committed_durable_owners_survive_old_object_reconciliation(
    db_session,
    test_settings,
    monkeypatch,
):
    referenced = await retained_image_keys(db_session, test_settings)
    assert len(referenced) == 26
    pages = {
        prefix: sorted((key, OLD) for key in referenced if key.startswith(prefix))
        for prefix in IMAGE_PREFIXES
    }
    for prefix in IMAGE_PREFIXES:
        pages[prefix].append((prefix + "crashed-before-publication.jpg", OLD))
    storage = FakeStorage(pages)
    result = await reconcile(storage, monkeypatch, db_session)
    deleted = {key for batch in storage.deleted for key in batch}
    assert deleted == {prefix + "crashed-before-publication.jpg" for prefix in IMAGE_PREFIXES}
    assert not referenced.intersection(deleted)
    assert (result.scanned_count, result.stale_candidate_count, result.deleted_count) == (30, 30, 4)


@pytest.mark.asyncio
async def test_lost_commit_acknowledgement_does_not_make_a_persisted_image_an_orphan(
    db_session,
    test_settings,
    monkeypatch,
):
    await retained_image_keys(db_session, test_settings)
    owner = await db_session.scalar(select(PassportSubmissionModel).limit(1))
    key = IMAGE_PREFIXES[0] + "committed-with-lost-ack.jpg"

    async def publish_then_lose_ack():
        owner.passport_photo_s3_key = key
        await db_session.commit()
        raise ConnectionError("synthetic lost COMMIT acknowledgement")

    with pytest.raises(ConnectionError, match="synthetic lost COMMIT"):
        await publish_then_lose_ack()
    storage = FakeStorage({IMAGE_PREFIXES[0]: [(key, OLD)]})
    result = await reconcile(storage, monkeypatch, db_session)
    assert await db_session.scalar(text("PRAGMA foreign_keys")) == 1
    assert result.scanned_count == result.stale_candidate_count == 1
    assert result.deleted_count == 0
    assert storage.deleted == []


@pytest.mark.asyncio
async def test_reference_queries_bound_parameters_rows_and_duplicate_candidates(
    db_session,
    test_settings,
    monkeypatch,
):
    referenced = await retained_image_keys(db_session, test_settings)
    monkeypatch.setattr(
        passport_orphan_reconciliation,
        "AsyncSessionFactory",
        async_sessionmaker(db_session.bind, expire_on_commit=False),
    )
    keys = sorted(referenced) + [IMAGE_PREFIXES[0] + f"absent-{i}.jpg" for i in range(76)]
    observed = []

    def capture(_conn, _cursor, statement, parameters, _context, _executemany):
        if statement.lstrip().startswith("SELECT"):
            observed.append((statement, len(parameters)))

    event.listen(db_session.bind.sync_engine, "before_cursor_execute", capture)
    try:
        actual = await passport_orphan_reconciliation._referenced_keys(
            IMAGE_PREFIXES[0],
            keys * 4,
        )
    finally:
        event.remove(db_session.bind.sync_engine, "before_cursor_execute", capture)
    assert actual == referenced
    assert len(observed) == 3  # 102 distinct candidates, 49 per bounded query.
    assert max(count for _, count in observed) == 980
    assert all(statement.count(" UNION ") == 19 for statement, _ in observed)


@pytest.mark.asyncio
async def test_scheduled_scanner_preserves_real_document_owners_and_old_namespace_dispatch(
    db_session,
    monkeypatch,
):
    referenced = await retained_document_keys(db_session)
    monkeypatch.setattr(
        orphan_reconciliation,
        "AsyncSessionFactory",
        async_sessionmaker(db_session.bind, expire_on_commit=False),
    )
    pages = {
        prefix: [(prefix + "retained.pdf", OLD), (prefix + "orphan.pdf", OLD)]
        for prefix in orphan_reconciliation.DOCUMENT_ORPHAN_PREFIXES
    }
    storage = FakeStorage(pages)
    result = await reconcile(storage, monkeypatch, db_session)
    assert result.deleted_count == 2
    assert {key for batch in storage.deleted for key in batch} == {
        prefix + "orphan.pdf" for prefix in orphan_reconciliation.DOCUMENT_ORPHAN_PREFIXES
    }
    assert not referenced.intersection(key for batch in storage.deleted for key in batch)


@pytest.mark.asyncio
async def test_incomplete_reference_database_fails_closed_before_any_image_delete(
    db_session,
    monkeypatch,
):
    # An unavailable/missing durable reference table is not evidence of absence.
    await db_session.execute(text("DROP TABLE passport_ecr_checks"))
    await db_session.commit()
    storage = FakeStorage({IMAGE_PREFIXES[0]: [(IMAGE_PREFIXES[0] + "old.jpg", OLD)]})
    with pytest.raises(OperationalError):
        await reconcile(storage, monkeypatch, db_session)
    assert storage.deleted == []
