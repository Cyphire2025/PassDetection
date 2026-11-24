"""The scheduled Celery entry recovers only aged, unheld staff-import objects."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from functools import partial

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.infrastructure.celery_async_runtime import CeleryAsyncRuntime
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.documents import cleanup_tasks, passport_orphan_reconciliation
from app.infrastructure.documents.storage_cleanup import StorageCleanupCipher
from tests.integration.passport_orphan_fixtures import retained_image_keys
from tests.integration.test_passport_orphan_reconciliation import NOW, OLD
from tests.unit.infrastructure.test_document_orphan_reconciliation import FakeCursor, FakeStorage

BULK_PREFIX = "passport-bulk/"


def import_key():
    return f"{BULK_PREFIX}{uuid.uuid4()}/{uuid.uuid4()}/{uuid.uuid4()}/{uuid.uuid4().hex}-front.jpg"


async def scheduled_reconcile(storage, monkeypatch, session, *, cursor=None):
    """Run the actual task and actual local runtime over synthetic storage/cursors."""
    monkeypatch.setattr(
        passport_orphan_reconciliation,
        "AsyncSessionFactory",
        async_sessionmaker(session.bind, expire_on_commit=False),
    )
    implementation = passport_orphan_reconciliation.reconcile_sensitive_storage_orphans
    monkeypatch.setattr(
        cleanup_tasks,
        "_reconcile_document_storage_orphans",
        partial(
            implementation,
            storage=storage,
            cursor_client=cursor or FakeCursor(),
            cursor_cipher=StorageCleanupCipher("synthetic-bulk-orphan-cursor"),
            now=NOW,
        ),
    )

    async def no_external_cleanup():
        pass

    runtime = CeleryAsyncRuntime(cleanup=no_external_cleanup)
    monkeypatch.setattr(cleanup_tasks, "celery_async_runtime", runtime)
    try:
        return await asyncio.to_thread(cleanup_tasks.reconcile_document_storage_orphans.run)
    finally:
        await asyncio.to_thread(runtime.shutdown)


@pytest.mark.parametrize("prefix", [BULK_PREFIX, "drafts/"])
async def test_scheduled_task_recovers_aged_crashed_attempt_and_preserves_grace(
    db_session,
    monkeypatch,
    prefix,
):
    cutoff = NOW - timedelta(hours=24)
    keys = [prefix + f"synthetic-attempt-{index}.jpg" for index in range(4)]
    storage = FakeStorage(
        {
            prefix: [
                (keys[0], cutoff),
                (keys[1], cutoff + timedelta(microseconds=1)),
                (keys[2], NOW + timedelta(days=1)),
                (keys[3], None),
            ]
        }
    )
    result = await scheduled_reconcile(storage, monkeypatch, db_session)
    assert storage.deleted == [[keys[0]]]
    assert result == {"scanned_count": 4, "stale_candidate_count": 1, "deleted_count": 1}


async def test_all_twenty_durable_columns_hold_bulk_originals_and_retained_variants(
    db_session,
    test_settings,
    monkeypatch,
):
    held = await retained_image_keys(db_session, test_settings, prefixes=(BULK_PREFIX,))
    assert len(held) == 26  # 20 columns, with four distinct job status rows.
    orphan = import_key()
    storage = FakeStorage({BULK_PREFIX: [(key, OLD) for key in sorted(held)] + [(orphan, OLD)]})
    result = await scheduled_reconcile(storage, monkeypatch, db_session)
    assert await db_session.scalar(text("PRAGMA foreign_keys")) == 1
    assert storage.deleted == [[orphan]]
    assert not held.intersection(key for batch in storage.deleted for key in batch)
    assert result == {"scanned_count": 27, "stale_candidate_count": 27, "deleted_count": 1}


async def test_committed_bulk_reference_survives_lost_acknowledgement(
    db_session,
    test_settings,
    monkeypatch,
):
    await retained_image_keys(db_session, test_settings)
    owner = await db_session.scalar(select(PassportSubmissionModel).limit(1))
    key = import_key()
    with pytest.raises(ConnectionError, match="lost COMMIT"):
        owner.passport_back_s3_key = key
        await db_session.commit()
        raise ConnectionError("Synthetic lost COMMIT acknowledgement")
    storage = FakeStorage({BULK_PREFIX: [(key, OLD)]})
    result = await scheduled_reconcile(storage, monkeypatch, db_session)
    assert result == {"scanned_count": 1, "stale_candidate_count": 1, "deleted_count": 0}
    assert storage.deleted == []


async def test_failed_provider_delete_keeps_cursor_for_next_scheduled_retry(
    db_session, monkeypatch
):
    key, cursor = import_key(), FakeCursor()
    storage = FakeStorage({BULK_PREFIX: [(key, OLD)]})
    original_delete = storage.delete_files

    async def unavailable(_keys):
        raise ConnectionError("Synthetic provider delete unavailable")

    storage.delete_files = unavailable
    with pytest.raises(ConnectionError, match="provider delete"):
        await scheduled_reconcile(storage, monkeypatch, db_session, cursor=cursor)
    assert storage.deleted == [] and cursor.set_calls == []
    storage.delete_files = original_delete
    assert (await scheduled_reconcile(storage, monkeypatch, db_session, cursor=cursor))[
        "deleted_count"
    ] == 1
    assert storage.deleted == [[key]]


async def test_unavailable_reference_owner_fails_closed_before_bulk_delete(db_session, monkeypatch):
    await db_session.execute(text("DROP TABLE passport_ecr_checks"))
    await db_session.commit()
    storage = FakeStorage({BULK_PREFIX: [(import_key(), OLD)]})
    with pytest.raises(OperationalError):
        await scheduled_reconcile(storage, monkeypatch, db_session)
    assert storage.deleted == []


async def test_neighbor_and_other_retained_namespaces_are_never_admitted(db_session, monkeypatch):
    prefixes = ["passport-bulk-neighbor/", "passport-bulk", "returning-drafts/", "travellers/"]
    storage = FakeStorage({prefix: [(prefix + "/protected.jpg", OLD)] for prefix in prefixes})
    result = await scheduled_reconcile(storage, monkeypatch, db_session)
    assert result == {"scanned_count": 0, "stale_candidate_count": 0, "deleted_count": 0}
    assert storage.deleted == []
