"""Temporary expiry obeys production's autoflush=False transaction ordering."""
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.application.travellers.draft_uploads import upload_draft_document
from app.infrastructure.database.models import PassportSubmissionModel, StorageCleanupJobModel
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerReturningDraftModel as Draft,
)
from app.infrastructure.documents.storage_cleanup import StorageCleanupCipher
from app.infrastructure.travellers import draft_orphans
from app.infrastructure.travellers.draft_expiry import expire_draft_assets
from tests.integration.test_draft_retention import Presence
from tests.integration.test_returning_drafts import MemoryStorage, draft_context


@pytest.fixture(autouse=True)
def synthetic_presence(monkeypatch):
    @asynccontextmanager
    async def absent():
        yield Presence()

    monkeypatch.setattr(draft_orphans, "draft_presence", absent)


async def expiry_context(session, settings):
    session.sync_session.autoflush = False
    service, _, _, person, token, _, secret, view = await draft_context(session, settings)
    storage = MemoryStorage()
    view = await upload_draft_document(service, token, secret, side="front", expected_revision=view.revision,
        idempotency_key=uuid.uuid4().hex, content=b"synthetic-expiry", content_type="image/jpeg", storage=storage)
    factory = async_sessionmaker(session.bind, expire_on_commit=False, autoflush=False)
    draft = await session.get(Draft, view.id)
    asset = await session.scalar(select(Asset).where(Asset.draft_id == view.id))
    return service, person, token, secret, view, storage, factory, draft, asset


@pytest.mark.asyncio
async def test_newly_expired_images_are_queued_in_the_same_tick_without_official_changes(db_session, test_settings):
    _, person, _, _, _, _, factory, draft, asset = await expiry_context(db_session, test_settings)
    official = (person.profile.revision, person.document.fields_ciphertext, person.asset.object_key, person.asset.availability)
    key = asset.object_key
    draft.created_at, draft.expires_at = datetime.now(UTC) - timedelta(days=2), datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    assert await expire_draft_assets(factory=factory) == 1
    await db_session.refresh(draft)
    await db_session.refresh(asset)
    assert draft.status == "expired" and draft.payload_ciphertext == ""
    assert asset.state == "discarded" and not asset.is_current
    jobs = list(await db_session.scalars(select(StorageCleanupJobModel)))
    assert len(jobs) == 1
    assert StorageCleanupCipher.from_settings().decrypt(jobs[0].storage_keys_ciphertext,
        key_version=jobs[0].encryption_key_version) == (key,)
    for row in (person.profile, person.document, person.asset):
        await db_session.refresh(row)
    assert (person.profile.revision, person.document.fields_ciphertext, person.asset.object_key, person.asset.availability) == official
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0


@pytest.mark.asyncio
async def test_orphan_pass_does_not_reload_and_queue_an_already_discarded_upload(db_session, test_settings):
    service, _, token, secret, view, storage, factory, draft, front = await expiry_context(db_session, test_settings)
    await upload_draft_document(service, token, secret, side="back", expected_revision=view.revision,
        idempotency_key=uuid.uuid4().hex, content=b"synthetic-back", content_type="image/jpeg", storage=storage)
    back = await db_session.scalar(select(Asset).where(Asset.draft_id == draft.id, Asset.side == "back"))
    front.state, front.is_current = "uploading", False
    front.created_at = back.created_at = datetime.now(UTC) - timedelta(minutes=31)
    original_text = draft.payload_ciphertext
    await db_session.commit()

    assert await expire_draft_assets(factory=factory) == 2
    await db_session.refresh(front)
    await db_session.refresh(back)
    await db_session.refresh(draft)
    assert front.state == back.state == "discarded"
    assert draft.status == "active" and draft.payload_ciphertext == original_text
    jobs = list(await db_session.scalars(select(StorageCleanupJobModel)))
    assert len(jobs) == 2 and len({job.context_fingerprint for job in jobs}) == 2


@pytest.mark.asyncio
async def test_expiring_a_submitted_draft_never_queues_its_adopted_image(db_session, test_settings):
    _, _, _, _, _, _, factory, draft, asset = await expiry_context(db_session, test_settings)
    key = asset.object_key
    draft.status, asset.state = "submitted", "adopted"
    draft.created_at, draft.expires_at = datetime.now(UTC) - timedelta(days=2), datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    assert await expire_draft_assets(factory=factory) == 0
    await db_session.refresh(asset)
    await db_session.refresh(draft)
    assert asset.state == "adopted" and asset.object_key == key
    assert draft.status == "expired" and draft.payload_ciphertext == ""
    assert await db_session.scalar(select(func.count()).select_from(StorageCleanupJobModel)) == 0
