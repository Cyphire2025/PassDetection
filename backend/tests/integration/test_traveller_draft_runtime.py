"""Bounded draft extraction is lease-fenced and expiry never deletes adopted files."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.interfaces.passport_extraction import PassportExtractionResult
from app.application.travellers.draft_contracts import DraftSave
from app.application.travellers.draft_uploads import upload_draft_document
from app.application.travellers.drafts import draft_payload, require_draft, save_draft
from app.infrastructure.database.models import StorageCleanupJobModel
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerReturningDraftModel as Draft,
)
from app.infrastructure.travellers.draft_extraction import DraftExtractionDeferred
from app.infrastructure.travellers.draft_runtime import (
    expire_draft_assets,
    reserve_extraction,
    run_draft_extraction,
)
from tests.integration.test_returning_drafts import MemoryStorage, draft_context


class StreamStorage(MemoryStorage):
    async def stream_file(self, key, *, start, expected_bytes):
        yield self.files[key]


class Extractor:
    def __init__(self, fields, callback=None, error=None):
        self.fields, self.callback, self.error = fields, callback, error

    async def extract(self, content, **kwargs):
        if self.callback:
            await self.callback()
        if self.error:
            raise self.error
        return PassportExtractionResult(self.fields, 0, {})


async def runtime_context(session, settings):
    service, _, _, _, token, review, secret, view = await draft_context(session, settings)
    storage = StreamStorage()
    view = await upload_draft_document(service, token, secret, side="front", expected_revision=view.revision,
        idempotency_key=uuid.uuid4().hex, content=b"bounded synthetic content", content_type="image/jpeg", storage=storage)
    factory = async_sessionmaker(session.bind, expire_on_commit=False)
    return service, token, review, secret, view, storage, factory


@pytest.mark.asyncio
async def test_worker_uses_bounded_temp_image_and_does_not_overwrite_newer_manual_edits(db_session, test_settings):
    service, token, _, secret, view, storage, factory = await runtime_context(db_session, test_settings)

    async def edit_during_extraction():
        await save_draft(service, token, secret, DraftSave(expected_revision=view.revision, idempotency_key=uuid.uuid4().hex,
            passport_fields={"given_names": "MANUALLY REVIEWED"}))

    extractor = Extractor({"given_names": "EXTRACTED", "ai_verification": {"status": "verified", "available": True}}, edit_during_extraction)
    assert await run_draft_extraction(factory=factory, storage=storage, extractor=extractor, crypto=service.crypto) == 1
    db_session.expire_all()
    draft = await require_draft(service, token, secret)
    assert draft_payload(service, draft).passport_fields["given_names"] == "MANUALLY REVIEWED"
    asset = await db_session.scalar(select(Asset).where(Asset.draft_id == draft.id))
    assert asset.extraction_status == "succeeded" and asset.attempts == 1


@pytest.mark.asyncio
async def test_priority_backpressure_does_not_consume_attempt(db_session, test_settings):
    service, _, _, _, view, storage, factory = await runtime_context(db_session, test_settings)
    await run_draft_extraction(factory=factory, storage=storage, extractor=Extractor({}, error=DraftExtractionDeferred()), crypto=service.crypto)
    asset = await db_session.scalar(select(Asset).where(Asset.draft_id == view.id).execution_options(populate_existing=True))
    assert asset.attempts == 0 and asset.extraction_status == "pending" and asset.lease_expires_at is None


@pytest.mark.asyncio
async def test_last_crashed_lease_becomes_terminal_and_stale_worker_cannot_publish(db_session, test_settings):
    service, _, _, _, view, storage, factory = await runtime_context(db_session, test_settings)
    asset = await db_session.scalar(select(Asset).where(Asset.draft_id == view.id))
    asset.attempts, asset.extraction_status = 3, "running"
    asset.available_at = asset.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    assert await reserve_extraction(factory) is None
    await db_session.refresh(asset)
    assert asset.extraction_status == "failed" and asset.lease_expires_at is None


@pytest.mark.asyncio
async def test_expiry_cleans_temporary_only_and_erases_draft_text(db_session, test_settings):
    service, _, _, _, view, _, factory = await runtime_context(db_session, test_settings)
    draft = await db_session.get(Draft, view.id)
    asset = await db_session.scalar(select(Asset).where(Asset.draft_id == draft.id))
    asset.state = "adopted"
    asset.classification_ciphertext = service.crypto.encrypt("sensitive classification")
    draft.status, draft.created_at, draft.expires_at = "submitted", datetime.now(UTC)-timedelta(days=2), datetime.now(UTC)-timedelta(seconds=1)
    await db_session.commit()
    assert await expire_draft_assets(factory=factory) == 0
    await db_session.refresh(asset)
    await db_session.refresh(draft)
    assert asset.state == "adopted" and asset.object_key and asset.classification_ciphertext is None
    assert draft.status == "expired" and draft.payload_ciphertext == ""
    assert await db_session.scalar(select(StorageCleanupJobModel.id)) is None


@pytest.mark.asyncio
async def test_expiry_stages_private_temp_cleanup(db_session, test_settings):
    _, _, _, _, view, _, factory = await runtime_context(db_session, test_settings)
    draft = await db_session.get(Draft, view.id)
    draft.created_at, draft.expires_at = datetime.now(UTC)-timedelta(days=2), datetime.now(UTC)-timedelta(seconds=1)
    await db_session.commit()
    assert await expire_draft_assets(factory=factory) == 1
    asset = await db_session.scalar(select(Asset).where(Asset.draft_id == view.id).execution_options(populate_existing=True))
    assert asset.state == "discarded" and not asset.is_current
    assert await db_session.scalar(select(StorageCleanupJobModel.id)) is not None
