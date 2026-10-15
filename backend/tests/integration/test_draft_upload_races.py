"""Different sides and OCR progress never invalidate an already reserved image."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.application.travellers.draft_contracts import DraftSave
from app.application.travellers.draft_retention import discard_draft_images
from app.application.travellers.draft_uploads import upload_draft_document
from app.application.travellers.drafts import draft_view, require_draft, save_draft
from app.application.travellers.errors import ReuseError, ReuseReason
from app.infrastructure.database.models import StorageCleanupJobModel
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from tests.integration.test_returning_drafts import MemoryStorage, draft_context


class DuringStorage(MemoryStorage):
    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    async def upload_file(self, content, key, media):
        await super().upload_file(content, key, media)
        await self.callback()


async def upload(service, token, secret, view, side, storage, **options):
    return await upload_draft_document(service, token, secret, side=side,
        expected_revision=view.revision, idempotency_key=options.pop("key", uuid.uuid4().hex),
        content=(side + " synthetic image").encode(), content_type="image/jpeg", storage=storage, **options)


@pytest.mark.asyncio
async def test_unrelated_autosave_during_image_io_does_not_discard_upload(db_session, test_settings):
    service, _, _, _, token, _, secret, view = await draft_context(db_session, test_settings)

    async def edit():
        await save_draft(service, token, secret, DraftSave(expected_revision=view.revision,
            idempotency_key=uuid.uuid4().hex, passport_fields=view.passport_fields,
            current_details={"client_email": "reviewed@example.com"}))

    result = await upload(service, token, secret, view, "back", DuringStorage(edit))
    assert result.current_details["client_email"] == "reviewed@example.com"
    assert result.documents[0].side == "back" and result.documents[0].state == "ready"
    assert await db_session.scalar(select(func.count()).select_from(StorageCleanupJobModel)) == 0


@pytest.mark.asyncio
async def test_two_different_sides_can_finish_in_reverse_order(db_session, test_settings):
    service, _, _, _, token, _, secret, view = await draft_context(db_session, test_settings)

    async def another_side():
        await upload(service, token, secret, view, "photo", MemoryStorage())

    result = await upload(service, token, secret, view, "back", DuringStorage(another_side))
    assert {image.side for image in result.documents} == {"back", "photo"}
    assert all(image.state == "ready" for image in result.documents)


@pytest.mark.asyncio
async def test_later_same_side_intent_wins_and_late_bytes_get_new_cleanup(db_session, test_settings):
    service, _, _, _, token, _, secret, view = await draft_context(db_session, test_settings)
    chosen = []

    async def newer_same_side():
        chosen.append(await upload(service, token, secret, view, "back", MemoryStorage()))
        # Simulate the first cleanup completing before the old storage call ends.
        job = await db_session.scalar(select(StorageCleanupJobModel))
        await db_session.delete(job)
        await db_session.commit()

    with pytest.raises(ReuseError) as denied:
        await upload(service, token, secret, view, "back", DuringStorage(newer_same_side))
    assert denied.value.reason == ReuseReason.REVISION_CONFLICT
    current = await draft_view(service, await require_draft(service, token, secret))
    assert current.documents == chosen[0].documents
    assert await db_session.scalar(select(func.count()).select_from(StorageCleanupJobModel)
        .where(StorageCleanupJobModel.status == "pending")) == 1


@pytest.mark.asyncio
async def test_front_reservation_hides_old_extraction_and_keeps_edits_during_io(db_session, test_settings):
    service, _, _, _, token, _, secret, view = await draft_context(db_session, test_settings)

    async def edit_new_front():
        current = await draft_view(service, await require_draft(service, token, secret))
        assert current.passport_fields == {} and current.extracted_fields == {}
        assert current.documents[0].state == "uploading"
        await save_draft(service, token, secret, DraftSave(expected_revision=current.revision,
            idempotency_key=uuid.uuid4().hex, passport_fields={"given_names": "CURRENT EDIT"}))

    result = await upload(service, token, secret, view, "front", DuringStorage(edit_new_front))
    assert result.passport_fields == {"given_names": "CURRENT EDIT"}
    assert result.extraction_status == "pending"


@pytest.mark.asyncio
async def test_stale_global_revision_can_replace_only_the_explicit_unchanged_side(db_session, test_settings):
    service, _, _, _, token, _, secret, view = await draft_context(db_session, test_settings)
    ready = await upload(service, token, secret, view, "back", MemoryStorage())
    side_id = ready.documents[0].id
    await upload(service, token, secret, ready, "photo", MemoryStorage())
    result = await upload(service, token, secret, ready, "back", MemoryStorage(), expected_asset_id=side_id)
    assert next(image.id for image in result.documents if image.side == "back") != side_id
    with pytest.raises(ReuseError):
        await upload(service, token, secret, result, "back", MemoryStorage(), expected_asset_id=side_id)


@pytest.mark.asyncio
async def test_retry_after_ambiguous_storage_failure_reuses_reservation(db_session, test_settings):
    service, _, _, _, token, _, secret, view = await draft_context(db_session, test_settings)
    async def failed_response():
        raise TimeoutError()
    key = uuid.uuid4().hex
    with pytest.raises(TimeoutError):
        await upload(service, token, secret, view, "front", DuringStorage(failed_response), key=key)
    result = await upload(service, token, secret, view, "front", MemoryStorage(), key=key)
    assert result.documents[0].state == "ready"
    assert await db_session.scalar(select(func.count()).select_from(Asset)) == 1


@pytest.mark.asyncio
async def test_scanner_request_from_before_discard_cannot_create_an_empty_side(db_session, test_settings):
    service, _, _, _, token, _, secret, view = await draft_context(db_session, test_settings)
    await discard_draft_images(service, await require_draft(service, token, secret))
    await db_session.commit()
    with pytest.raises(ReuseError):
        await upload(service, token, secret, view, "back", MemoryStorage())
    assert await db_session.scalar(select(func.count()).select_from(Asset)) == 0


@pytest.mark.asyncio
async def test_stale_leave_cutoff_cannot_remove_a_later_side_cas_reservation(db_session, test_settings):
    service, _, _, _, token, _, secret, view = await draft_context(db_session, test_settings)
    ready = await upload(service, token, secret, view, "back", MemoryStorage())
    side_id = ready.documents[0].id
    await save_draft(service, token, secret, DraftSave(expected_revision=ready.revision,
        idempotency_key=uuid.uuid4().hex, passport_fields=ready.passport_fields,
        current_details={"client_email": "newer@example.com"}))
    replacement = await upload(service, token, secret, ready, "back", MemoryStorage(), expected_asset_id=side_id)
    await discard_draft_images(service, await require_draft(service, token, secret), through_revision=ready.revision)
    await db_session.commit()
    result = await draft_view(service, await require_draft(service, token, secret))
    assert result.documents == replacement.documents


@pytest.mark.asyncio
async def test_uploading_replacement_wins_even_if_transaction_timestamp_precedes_current(db_session, test_settings):
    service, _, _, _, token, _, secret, view = await draft_context(db_session, test_settings)
    ready = await upload(service, token, secret, view, "back", MemoryStorage())

    async def inspect_reservation():
        # PostgreSQL now() is transaction-start time, not lock-acquisition order.
        reservation = await db_session.scalar(select(Asset).where(Asset.state == "uploading"))
        reservation.created_at = datetime.now(UTC) - timedelta(days=1)
        await db_session.flush()
        current = await draft_view(service, await require_draft(service, token, secret))
        assert current.documents[0].state == "uploading"
        assert current.documents[0].id == reservation.id

    await upload(service, token, secret, ready, "back", DuringStorage(inspect_reservation),
        expected_asset_id=ready.documents[0].id)
