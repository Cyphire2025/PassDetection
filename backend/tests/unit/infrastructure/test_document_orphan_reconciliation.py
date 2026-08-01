from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.infrastructure.documents.orphan_reconciliation import (
    DOCUMENT_ORPHAN_CURSOR_TTL_SECONDS,
    DOCUMENT_ORPHAN_PAGE_SIZE,
    DocumentOrphanReconciliationResult,
    reconcile_document_storage_orphans,
)
from app.infrastructure.documents.storage_cleanup import StorageCleanupCipher


class FakeStorage:
    def __init__(self, pages: dict[str, list[tuple[str, datetime | None]]]) -> None:
        self.pages = pages
        self.deleted: list[list[str]] = []

    async def list_files(
        self,
        *,
        prefix: str,
        limit: int,
        start_after: str | None = None,
    ) -> list[tuple[str, datetime | None]]:
        assert limit == DOCUMENT_ORPHAN_PAGE_SIZE
        values = self.pages.get(prefix, [])
        return [item for item in values if start_after is None or item[0] > start_after][:limit]

    async def delete_files(self, keys: list[str]) -> int:
        self.deleted.append(keys)
        return len(keys)


class FakeCursor:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.set_calls: list[tuple[str, int, str]] = []

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        self.values[key] = value
        self.set_calls.append((key, ttl, value))


@pytest.mark.asyncio
async def test_reconciler_deletes_only_old_unreferenced_fixed_namespace_keys() -> None:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    old = now - timedelta(days=2)
    recent = now - timedelta(hours=1)
    storage = FakeStorage(
        {
            "document-rename/": [
                ("document-rename/batch/orphan.pdf", old),
                ("document-rename/batch/referenced.pdf", old),
                ("document-rename/batch/recent.pdf", recent),
                ("document-rename/batch/unknown-age.pdf", None),
            ],
            "document-distribution/": [],
        }
    )

    async def references(prefix: str, keys: Any) -> set[str]:
        assert prefix in {"document-rename/", "document-distribution/"}
        return {key for key in keys if key.endswith("referenced.pdf")}

    cipher = StorageCleanupCipher("orphan-cursor-test-secret")
    result = await reconcile_document_storage_orphans(
        storage=storage,  # type: ignore[arg-type]
        reference_lookup=references,
        cursor_client=FakeCursor(),
        cursor_cipher=cipher,
        now=now,
    )

    assert storage.deleted == [["document-rename/batch/orphan.pdf"]]
    assert result.scanned_count == 4
    assert result.stale_candidate_count == 2
    assert result.deleted_count == 1


@pytest.mark.asyncio
async def test_reconciler_advances_a_bounded_cursor_for_full_pages() -> None:
    now = datetime(2026, 8, 1, tzinfo=UTC)
    recent = now - timedelta(minutes=1)
    objects = [
        (f"document-rename/batch/{index:04d}.pdf", recent)
        for index in range(DOCUMENT_ORPHAN_PAGE_SIZE)
    ]
    storage = FakeStorage(
        {
            "document-rename/": objects,
            "document-distribution/": [],
        }
    )
    cursor = FakeCursor()
    cipher = StorageCleanupCipher("orphan-cursor-test-secret")

    async def no_references(_prefix: str, _keys: Any) -> set[str]:
        return set()

    await reconcile_document_storage_orphans(
        storage=storage,  # type: ignore[arg-type]
        reference_lookup=no_references,
        cursor_client=cursor,
        cursor_cipher=cipher,
        now=now,
    )

    assert cursor.set_calls
    _, ttl, value = cursor.set_calls[0]
    assert ttl == DOCUMENT_ORPHAN_CURSOR_TTL_SECONDS
    assert objects[-1][0] not in value
    version_text, encoded = value.split(":", 1)
    assert cipher.decrypt(
        base64.urlsafe_b64decode(encoded),
        key_version=int(version_text),
    ) == (objects[-1][0],)
    assert storage.deleted == []


def test_celery_task_returns_only_aggregate_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.infrastructure.documents import cleanup_tasks

    awaitable_marker = object()
    expected = DocumentOrphanReconciliationResult(
        scanned_count=37,
        stale_candidate_count=4,
        deleted_count=3,
    )
    observed: list[object] = []

    monkeypatch.setattr(
        cleanup_tasks,
        "_reconcile_document_storage_orphans",
        lambda: awaitable_marker,
    )

    def run(awaitable: object) -> DocumentOrphanReconciliationResult:
        observed.append(awaitable)
        return expected

    monkeypatch.setattr(cleanup_tasks.celery_async_runtime, "run", run)

    assert cleanup_tasks.reconcile_document_storage_orphans.run() == {
        "scanned_count": 37,
        "stale_candidate_count": 4,
        "deleted_count": 3,
    }
    assert observed == [awaitable_marker]
