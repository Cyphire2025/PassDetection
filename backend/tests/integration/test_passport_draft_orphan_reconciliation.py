"""Aged upload-attempt drafts: real durable references with synthetic storage."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, text

from app.application.use_cases.passports.submit_passport_use_case import SubmitPassportUseCase
from app.infrastructure.database.models import PassportSubmissionModel
from tests.integration.passport_orphan_fixtures import retained_image_keys
from tests.integration.test_passport_orphan_reconciliation import NOW, OLD, reconcile
from tests.unit.infrastructure.test_document_orphan_reconciliation import FakeStorage

DRAFT_PREFIX = "drafts/"


def attempt_key():
    return SubmitPassportUseCase._draft_key(
        agency_id=uuid.uuid4(),
        group_id=uuid.uuid4(),
        unique_id=uuid.uuid4(),
        document_type="cover",
        content_type="image/png",
    )


class RetryStorage(FakeStorage):
    failed_once = False

    async def delete_files(self, keys):
        if not self.failed_once:
            self.failed_once = True
            raise ConnectionError("synthetic provider delete failure")
        return await super().delete_files(keys)


@pytest.mark.asyncio
async def test_scheduled_cleanup_recovers_aged_attempt_after_best_effort_delete_failure(
    db_session,
    monkeypatch,
):
    key = attempt_key()
    storage = RetryStorage({DRAFT_PREFIX: [(key, OLD)]})
    use_case = object.__new__(SubmitPassportUseCase)
    use_case._storage_repo = storage
    await use_case._cleanup_uploads([key])
    assert storage.failed_once and storage.deleted == []
    result = await reconcile(storage, monkeypatch, db_session)
    assert storage.deleted == [[key]]
    assert (result.scanned_count, result.stale_candidate_count, result.deleted_count) == (1, 1, 1)


@pytest.mark.asyncio
async def test_every_durable_image_owner_also_holds_aged_upload_draft_keys(
    db_session,
    test_settings,
    monkeypatch,
):
    held = await retained_image_keys(db_session, test_settings, prefixes=(DRAFT_PREFIX,))
    assert len(held) == 26
    storage = FakeStorage({DRAFT_PREFIX: [(key, OLD) for key in sorted(held)]})
    result = await reconcile(storage, monkeypatch, db_session)
    assert await db_session.scalar(text("PRAGMA foreign_keys")) == 1
    assert result.scanned_count == result.stale_candidate_count == 26
    assert result.deleted_count == 0 and storage.deleted == []


@pytest.mark.asyncio
async def test_committed_draft_is_held_after_a_lost_commit_acknowledgement(
    db_session,
    test_settings,
    monkeypatch,
):
    await retained_image_keys(db_session, test_settings)
    owner = await db_session.scalar(select(PassportSubmissionModel).limit(1))
    key = attempt_key()

    async def publish_then_lose_ack():
        owner.passport_cover_s3_key = key
        await db_session.commit()
        raise ConnectionError("synthetic lost COMMIT acknowledgement")

    with pytest.raises(ConnectionError, match="synthetic lost COMMIT"):
        await publish_then_lose_ack()
    storage = FakeStorage({DRAFT_PREFIX: [(key, OLD)]})
    result = await reconcile(storage, monkeypatch, db_session)
    assert result.scanned_count == result.stale_candidate_count == 1
    assert result.deleted_count == 0 and storage.deleted == []


@pytest.mark.asyncio
async def test_draft_scan_keeps_recent_future_and_unknown_age_attempts(
    db_session,
    monkeypatch,
):
    cutoff = NOW - timedelta(hours=24)
    old_key, recent, future, unknown = [attempt_key() for _ in range(4)]
    storage = FakeStorage(
        {
            DRAFT_PREFIX: [
                (old_key, cutoff),
                (recent, cutoff + timedelta(microseconds=1)),
                (future, NOW + timedelta(days=1)),
                (unknown, None),
            ]
        }
    )
    result = await reconcile(storage, monkeypatch, db_session)
    assert storage.deleted == [[old_key]]
    assert (result.scanned_count, result.stale_candidate_count, result.deleted_count) == (4, 1, 1)
