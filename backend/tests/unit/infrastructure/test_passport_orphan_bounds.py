"""Failure, grace and cursor controls for the existing bounded cleanup engine."""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.infrastructure.documents import orphan_reconciliation as engine
from app.infrastructure.documents import passport_orphan_reconciliation as images
from app.infrastructure.documents.storage_cleanup import StorageCleanupCipher
from tests.unit.infrastructure.test_document_orphan_reconciliation import FakeCursor, FakeStorage

NOW = datetime(2026, 10, 31, tzinfo=UTC)
PREFIX = images.PASSPORT_IMAGE_ORPHAN_PREFIXES[0]
CIPHER = StorageCleanupCipher("synthetic-orphan-bounds-cursor")


async def no_references(_prefix, _keys):
    return set()


async def scan(storage, cursor=None, **kwargs):
    return await images.reconcile_sensitive_storage_orphans(
        storage=storage,
        cursor_client=cursor or FakeCursor(),
        cursor_cipher=CIPHER,
        now=NOW,
        reference_lookup=no_references,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_grace_preserves_recent_future_unknown_and_handles_utc_boundaries():
    cutoff = NOW - timedelta(hours=24)
    storage = FakeStorage(
        {
            PREFIX: [
                (PREFIX + "recent", cutoff + timedelta(microseconds=1)),
                (PREFIX + "future", NOW + timedelta(days=2)),
                (PREFIX + "unknown", None),
                (PREFIX + "boundary", cutoff),
                (PREFIX + "naive", cutoff.replace(tzinfo=None)),
                (PREFIX + "offset", cutoff.astimezone(timezone(timedelta(hours=5, minutes=30)))),
            ]
        }
    )
    result = await scan(storage)
    assert storage.deleted == [[PREFIX + name for name in ("boundary", "naive", "offset")]]
    assert (result.scanned_count, result.stale_candidate_count, result.deleted_count) == (6, 3, 3)


@pytest.mark.asyncio
async def test_image_cursor_rotates_past_a_full_recent_page_and_keeps_keys_encrypted():
    recent = [(PREFIX + f"{i:04d}.jpg", NOW) for i in range(engine.DOCUMENT_ORPHAN_PAGE_SIZE)]
    tail = PREFIX + "zz-orphan.jpg"
    storage = FakeStorage({PREFIX: recent + [(tail, NOW - timedelta(days=2))]})
    cursor = FakeCursor()
    first = await scan(storage, cursor)
    assert first.scanned_count == engine.DOCUMENT_ORPHAN_PAGE_SIZE
    assert storage.deleted == []
    _, ttl, value = cursor.set_calls[0]
    assert ttl == engine.DOCUMENT_ORPHAN_CURSOR_TTL_SECONDS
    assert recent[-1][0] not in value
    version, encoded = value.split(":", 1)
    assert CIPHER.decrypt(base64.urlsafe_b64decode(encoded), key_version=int(version)) == (
        recent[-1][0],
    )
    second = await scan(storage, cursor)
    assert (second.scanned_count, second.deleted_count) == (1, 1)
    assert storage.deleted == [[tail]]
    assert engine._cursor_key(PREFIX) not in cursor.values


@pytest.mark.asyncio
async def test_delete_requests_are_bounded_to_the_existing_batch_size():
    old = NOW - timedelta(days=2)
    keys = [PREFIX + f"{i}.jpg" for i in range(551)]
    storage = FakeStorage({PREFIX: [(key, old) for key in keys]})
    result = await scan(storage)
    assert list(map(len, storage.deleted)) == [250, 250, 51]
    assert [key for batch in storage.deleted for key in batch] == keys
    assert result.deleted_count == 551


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["list", "reference", "delete"])
async def test_failures_leave_image_cursor_unadvanced_for_safe_retry(failure):
    storage = FakeStorage({PREFIX: [(PREFIX + "old.jpg", NOW - timedelta(days=2))]})
    cursor = FakeCursor()
    original_list, original_delete = storage.list_files, storage.delete_files

    async def list_files(**kwargs):
        if failure == "list" and kwargs["prefix"] == PREFIX:
            raise RuntimeError("synthetic list failure")
        return await original_list(**kwargs)

    async def references(prefix, _keys):
        if failure == "reference" and prefix == PREFIX:
            raise RuntimeError("synthetic database failure")
        return set()

    async def delete_files(keys):
        if failure == "delete":
            raise RuntimeError("synthetic delete failure")
        return await original_delete(keys)

    storage.list_files, storage.delete_files = list_files, delete_files
    with pytest.raises(RuntimeError, match="synthetic"):
        await images.reconcile_sensitive_storage_orphans(
            storage=storage,
            cursor_client=cursor,
            cursor_cipher=CIPHER,
            now=NOW,
            reference_lookup=references,
        )
    assert cursor.set_calls == []
    assert storage.deleted == []


@pytest.mark.asyncio
@pytest.mark.parametrize("cursor_value", [None, b"bad:cursor", "bad:cursor", "wrong-namespace"])
async def test_invalid_or_foreign_cursors_cannot_skip_the_image_namespace(cursor_value):
    cursor = FakeCursor()
    if cursor_value == "wrong-namespace":
        encrypted = CIPHER.encrypt(["document-rename/foreign.jpg"])
        cursor_value = f"{CIPHER.key_version}:" + base64.urlsafe_b64encode(encrypted).decode()
    cursor.values[engine._cursor_key(PREFIX)] = cursor_value
    storage = FakeStorage({PREFIX: [(PREFIX + "old.jpg", NOW - timedelta(days=2))]})
    assert (await scan(storage, cursor)).deleted_count == 1


@pytest.mark.asyncio
async def test_cursor_outage_rescans_safely_and_does_not_disclose_object_keys(monkeypatch):
    cursor = FakeCursor()
    cursor.get = AsyncMock(side_effect=RuntimeError("synthetic private detail"))
    cursor.delete = AsyncMock(side_effect=RuntimeError("synthetic private detail"))
    logger = SimpleNamespace(warning=[])  # Capture structured projections, not rendered text.
    monkeypatch.setattr(engine.logger, "warning", lambda *a, **kw: logger.warning.append((a, kw)))
    key = PREFIX + "synthetic-private-name.jpg"
    result = await scan(FakeStorage({PREFIX: [(key, NOW - timedelta(days=2))]}), cursor)
    assert result.deleted_count == 1
    assert logger.warning
    assert key not in str(logger.warning)
    assert "synthetic private detail" not in str(logger.warning)


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_internally_created_cursor_closes_on_success_and_failure(monkeypatch, failed):
    cursor = FakeCursor()
    cursor.aclose = AsyncMock()
    monkeypatch.setattr(engine, "Redis", SimpleNamespace(from_url=lambda *_a, **_kw: cursor))

    async def references(_prefix, _keys):
        if failed:
            raise RuntimeError("synthetic database failure")
        return set()

    call = images.reconcile_sensitive_storage_orphans(
        storage=FakeStorage({}),
        reference_lookup=references,
        now=NOW,
    )
    if failed:
        with pytest.raises(RuntimeError):
            await call
    else:
        assert (await call).deleted_count == 0
    cursor.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_reference_lookup_rejects_unknown_prefixes_and_skips_empty_database_work(monkeypatch):
    factory = AsyncMock(side_effect=AssertionError("must not open a database"))
    monkeypatch.setattr(images, "AsyncSessionFactory", factory)
    assert await images._referenced_keys(PREFIX, []) == set()
    with pytest.raises(ValueError, match="Unsupported passport image"):
        await images._referenced_keys("unowned/", ["unowned/image.jpg"])
    factory.assert_not_called()
