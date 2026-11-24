"""A cancelled upload thread cannot recreate an already-cleaned private image."""

import asyncio
import threading
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.travellers import draft_uploads
from app.application.travellers.draft_retention import discard_draft_images
from app.application.travellers.drafts import require_draft
from app.infrastructure.database.models import StorageCleanupJobModel
from app.infrastructure.documents.storage_cleanup import process_due_storage_cleanup_jobs
from tests.integration.test_returning_drafts import draft_context


class DelayedThreadStorage:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.finished = threading.Event()
        self.files = {}

    async def upload_file(self, content, key, media):
        def put():
            self.started.set()
            if self.release.wait(timeout=5):
                self.files[key] = content
            self.finished.set()

        await asyncio.to_thread(put)

    async def delete_files(self, keys):
        for key in keys:
            self.files.pop(key, None)
        return len(keys)


async def test_discard_waits_out_a_cancelled_thread_before_consuming_cleanup_intent(
    db_session,
    test_settings,
    monkeypatch,
):
    service, _, _, _, token, _, secret, view = await draft_context(db_session, test_settings)
    storage = DelayedThreadStorage()
    timeout = asyncio.timeout
    monkeypatch.setattr(
        draft_uploads.asyncio,
        "timeout",
        lambda seconds: timeout(0.05 if seconds == 30 else seconds),
    )
    upload = asyncio.create_task(
        draft_uploads.upload_draft_document(
            service,
            token,
            secret,
            side="back",
            expected_revision=view.revision,
            idempotency_key=uuid.uuid4().hex,
            content=b"synthetic-private-image",
            content_type="image/jpeg",
            storage=storage,
        )
    )
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    try:
        assert await asyncio.to_thread(storage.started.wait, 2)
        draft = await require_draft(service, token, secret)
        assert await discard_draft_images(service, draft) == 1
        await db_session.commit()
        with pytest.raises(TimeoutError):
            await upload
        assert (
            await process_due_storage_cleanup_jobs(
                session_factory=factory,
                storage_factory=lambda: storage,
            )
            == 0
        )
        storage.release.set()
        assert await asyncio.to_thread(storage.finished.wait, 2)
        assert len(storage.files) == 1
        marker = await db_session.scalar(select(StorageCleanupJobModel))
        assert marker is not None
        marker.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        await db_session.commit()
        assert (
            await process_due_storage_cleanup_jobs(
                session_factory=factory,
                storage_factory=lambda: storage,
            )
            == 1
        )
        assert not storage.files
    finally:
        storage.release.set()
        await asyncio.to_thread(storage.finished.wait, 2)
        if not upload.done():
            upload.cancel()
            with pytest.raises(asyncio.CancelledError):
                await upload
