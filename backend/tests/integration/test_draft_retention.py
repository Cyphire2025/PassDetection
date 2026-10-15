"""Abandoned photos are isolated from saved text and official documents."""
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import func, select

from app.application.travellers.draft_activity import record_draft_activity
from app.application.travellers.draft_retention import (
    discard_draft_images,
    stage_draft_asset_cleanup,
)
from app.application.travellers.draft_uploads import upload_draft_document
from app.application.travellers.drafts import draft_view, require_draft, save_draft, start_draft
from app.application.travellers.errors import ReuseError
from app.infrastructure.database.models import PassportSubmissionModel, StorageCleanupJobModel
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.travellers import draft_orphans
from app.infrastructure.travellers.draft_orphans import _scan_orphans
from tests.integration.test_returning_drafts import MemoryStorage, draft_context, save_body


async def uploaded(session, settings, side="back"):
    values = await draft_context(session, settings)
    service, _, _, person, token, review, secret, view = values
    view = await upload_draft_document(service, token, secret, side=side, expected_revision=view.revision,
        idempotency_key=uuid.uuid4().hex, content=b"synthetic-only", content_type="image/jpeg", storage=MemoryStorage())
    return service, person, token, review, secret, view


class Presence:
    def __init__(self, active=(), fail=False):
        self.active_ids, self.fail = set(active), fail
        self.position = None

    async def cursor(self):
        if self.fail:
            raise RedisConnectionError("synthetic unavailable")
        return self.position

    async def active(self, owners):
        return self.active_ids

    async def advance(self, cursor):
        self.position = cursor


@pytest.mark.asyncio
async def test_resume_discards_only_temporary_images_preserves_text_history(db_session, test_settings):
    service, person, token, review, secret, view = await uploaded(db_session, test_settings)
    original = (person.document.fields_ciphertext, person.asset.object_key, person.profile.revision)
    view = await save_draft(service, token, secret, save_body(view, current_details={"staff_code": "SYNTHETIC"}))
    _, resumed = await start_draft(service, token, expected_review_version=review["review_version"], existing_secret=secret)
    assert resumed.documents == [] and resumed.current_details == view.current_details
    assert resumed.passport_fields == view.passport_fields and resumed.extracted_fields == {}
    asset = await db_session.scalar(select(Asset).where(Asset.draft_id == resumed.id))
    assert asset.state == "discarded" and asset.lease_expires_at is None
    assert (person.document.fields_ciphertext, person.asset.object_key, person.profile.revision) == original
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0
    assert await db_session.scalar(select(func.count()).select_from(StorageCleanupJobModel)) == 1


@pytest.mark.asyncio
async def test_stale_leave_cannot_discard_upload_from_resumed_generation(db_session, test_settings):
    service, _, token, review, secret, view = await uploaded(db_session, test_settings)
    cutoff = view.revision
    _, resumed = await start_draft(service, token, expected_review_version=review["review_version"], existing_secret=secret)
    latest = await upload_draft_document(service, token, secret, side="back", expected_revision=resumed.revision,
        idempotency_key=uuid.uuid4().hex, content=b"new-view", content_type="image/jpeg", storage=MemoryStorage())
    draft = await require_draft(service, token, secret)
    assert await discard_draft_images(service, draft, through_revision=cutoff) == 0
    retained = await draft_view(service, draft)
    assert retained.documents == latest.documents and retained.revision == latest.revision


@pytest.mark.asyncio
async def test_leave_invalidates_running_extraction_and_never_cleans_adopted(db_session, test_settings):
    service, _, token, _, secret, view = await uploaded(db_session, test_settings, side="front")
    draft = await require_draft(service, token, secret)
    asset = await db_session.scalar(select(Asset).where(Asset.draft_id == draft.id))
    asset.extraction_status, asset.lease_expires_at = "running", datetime.now(UTC) + timedelta(seconds=60)
    assert await discard_draft_images(service, draft, through_revision=view.revision) == 1
    assert asset.state == "discarded" and asset.lease_expires_at is None and asset.extraction_status == "none"
    asset.state = "adopted"
    with pytest.raises(ReuseError):
        stage_draft_asset_cleanup(db_session, asset)
    draft.status = "submitted"
    assert await discard_draft_images(service, draft) == 0
    assert asset.state == "adopted"


@pytest.mark.asyncio
async def test_cleanup_rejects_any_non_draft_storage_key(db_session, test_settings):
    service, person, token, _, secret, _ = await uploaded(db_session, test_settings)
    draft = await require_draft(service, token, secret)
    asset = await db_session.scalar(select(Asset).where(Asset.draft_id == draft.id))
    asset.object_key = person.asset.object_key
    with pytest.raises(ReuseError):
        await discard_draft_images(service, draft)
    assert asset.state == "ready"
    assert await db_session.scalar(select(func.count()).select_from(StorageCleanupJobModel)) == 0


@pytest.mark.asyncio
async def test_orphan_sweep_preserves_present_form_then_discards_after_presence_expires(db_session, test_settings):
    service, _, token, _, secret, view = await uploaded(db_session, test_settings)
    draft = await require_draft(service, token, secret)
    asset = await db_session.scalar(select(Asset).where(Asset.draft_id == draft.id))
    asset.created_at = datetime.now(UTC) - timedelta(minutes=31)
    before = draft.payload_ciphertext
    await db_session.commit()
    assert await _scan_orphans(db_session, Presence(active=[draft.id]), 100) == 0
    assert asset.state == "ready"
    assert await _scan_orphans(db_session, Presence(), 100) == 1
    assert asset.state == "discarded" and draft.payload_ciphertext == before
    assert (await draft_view(service, draft)).passport_fields == view.passport_fields


@pytest.mark.asyncio
async def test_presence_outage_defers_orphan_deletion(db_session, test_settings, monkeypatch):
    _, _, _, _, _, view = await uploaded(db_session, test_settings)
    asset = await db_session.scalar(select(Asset).where(Asset.draft_id == view.id))
    asset.created_at = datetime.now(UTC) - timedelta(minutes=31)
    await db_session.commit()

    @asynccontextmanager
    async def unavailable():
        yield Presence(fail=True)

    monkeypatch.setattr(draft_orphans, "draft_presence", unavailable)
    assert await draft_orphans.discard_orphan_images(db_session) == 0
    assert asset.state == "ready"
    assert await db_session.scalar(select(func.count()).select_from(StorageCleanupJobModel)) == 0


@pytest.mark.asyncio
async def test_activity_records_no_presence_when_there_are_no_staged_images(db_session, test_settings):
    service, _, _, _, token, _, secret, _ = await draft_context(db_session, test_settings)
    result = await record_draft_activity(service, await require_draft(service, token, secret))
    assert not result.images_present and not result.presence_recorded


@pytest.mark.asyncio
async def test_keyset_sweep_advances_past_open_forms_without_starving_orphans(db_session, test_settings):
    _, _, _, _, _, first = await uploaded(db_session, test_settings)
    _, _, _, _, _, second = await uploaded(db_session, test_settings)
    one = await db_session.scalar(select(Asset).where(Asset.draft_id == first.id))
    two = await db_session.scalar(select(Asset).where(Asset.draft_id == second.id))
    one.created_at = datetime.now(UTC) - timedelta(minutes=32)
    two.created_at = datetime.now(UTC) - timedelta(minutes=31)
    await db_session.commit()
    presence = Presence(active=[first.id])
    assert await _scan_orphans(db_session, presence, 1) == 0
    assert presence.position[1] == one.id
    assert await _scan_orphans(db_session, presence, 1) == 1
    assert one.state == "ready" and two.state == "discarded"
    assert await _scan_orphans(db_session, presence, 1) == 0
    assert presence.position is None


@pytest.mark.asyncio
async def test_future_leave_revision_is_rejected_without_scheduling_deletion(db_session, test_settings):
    service, _, token, _, secret, view = await uploaded(db_session, test_settings)
    draft = await require_draft(service, token, secret)
    with pytest.raises(ReuseError):
        await discard_draft_images(service, draft, through_revision=view.revision + 1)
    asset = await db_session.scalar(select(Asset).where(Asset.draft_id == view.id))
    assert asset.state == "ready"
    assert await db_session.scalar(select(func.count()).select_from(StorageCleanupJobModel)) == 0
