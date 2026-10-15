"""Current photo and qualifier collection retain an unchanged approved passport."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.application.travellers.draft_completion import complete_draft
from app.application.travellers.draft_uploads import upload_draft_document
from app.application.travellers.drafts import save_draft, start_draft
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.fresh_draft_contracts import FreshCollection
from app.application.travellers.history import read_history
from app.application.travellers.requirements import missing_document_requirements
from app.application.use_cases.client_groups.create_qualifier_selection_use_case import (
    CreateQualifierSelectionUseCase,
)
from app.domain.exceptions.exceptions import ValidationError
from app.infrastructure.database.models import PassportSubmissionModel, QualifierSelectionModel
from app.infrastructure.repositories.client_group_repository import ClientGroupRepository
from app.infrastructure.repositories.qualifier_selection_repository import (
    QualifierSelectionRepository,
)
from tests.integration.test_returning_completion import completion_context
from tests.integration.test_returning_drafts import MemoryStorage, completion_body, save_body


async def collection_context(session, settings, *, photo=False, qualifier=False):
    service, _, group, person, token, _ = await completion_context(session, settings)
    group.require_selfie = photo
    group.relation_with_qualifier_enabled = qualifier
    group.allow_files_from_device = False
    group.upload_configuration = {"passport_upload_pages": ["front"], "visa_photo_required": photo,
        "visa_photo_live_capture": True, "visa_photo_upload": False}
    await session.commit()
    review = await read_history(service, token)
    secret, view = await start_draft(service, token, expected_review_version=review["review_version"])
    return service, group, person, token, review, secret, view


async def qualifier_choice(service, group):
    use_case = CreateQualifierSelectionUseCase(ClientGroupRepository(service.session), QualifierSelectionRepository(service.session))
    result = await use_case.execute(group_token=group.token, is_self=True, relation_code=None)
    await service.session.commit()
    return result.selection_token


@pytest.mark.asyncio
async def test_fresh_camera_photo_does_not_require_unchanged_passport_reupload(db_session, test_settings):
    service, group, person, token, review, secret, view = await collection_context(db_session, test_settings, photo=True)
    original = person.document.fields_ciphertext
    view = await save_draft(service, token, secret, save_body(view, collection=FreshCollection(visa_photo_source="camera")))
    view = await upload_draft_document(service, token, secret, side="photo", expected_revision=view.revision,
        idempotency_key=uuid.uuid4().hex, content=b"synthetic camera photo", content_type="image/jpeg", storage=MemoryStorage())
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0
    result = await complete_draft(service, token, secret, completion_body(review, view))
    source = await db_session.get(PassportSubmissionModel, result[2])
    assert source.image_s3_key == person.asset.object_key
    assert source.passport_photo_s3_key.startswith("returning-drafts/") and source.status == "submitted"
    assert person.document.fields_ciphertext == original and person.profile.revision == 1


@pytest.mark.asyncio
async def test_new_photo_still_obeys_capture_method_policy(db_session, test_settings):
    service, _, _, token, review, secret, view = await collection_context(db_session, test_settings, photo=True)
    view = await save_draft(service, token, secret, save_body(view, collection=FreshCollection(visa_photo_source="file")))
    view = await upload_draft_document(service, token, secret, side="photo", expected_revision=view.revision,
        idempotency_key=uuid.uuid4().hex, content=b"synthetic file photo", content_type="image/jpeg", storage=MemoryStorage())
    with pytest.raises(ValidationError) as denied:
        await complete_draft(service, token, secret, completion_body(review, view))
    assert denied.value.field == "visa_photo_source"
    await db_session.rollback()
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0


@pytest.mark.asyncio
async def test_photo_cannot_bypass_passport_validity_for_this_trip(db_session, test_settings):
    service, group, person, token, _, secret, view = await collection_context(db_session, test_settings, photo=True)
    person.document.expiry_date = group.travel_date + timedelta(days=10)
    await db_session.commit()
    review = await read_history(service, token)
    assert review["suitability"]["outcome"] == "replacement_required"
    secret, view = await start_draft(service, token, expected_review_version=review["review_version"], existing_secret=secret)
    view = await save_draft(service, token, secret, save_body(view, collection=FreshCollection(visa_photo_source="camera")))
    view = await upload_draft_document(service, token, secret, side="photo", expected_revision=view.revision,
        idempotency_key=uuid.uuid4().hex, content=b"synthetic current photo", content_type="image/jpeg", storage=MemoryStorage())
    with pytest.raises(ReuseError) as denied:
        await complete_draft(service, token, secret, completion_body(review, view))
    assert denied.value.reason == ReuseReason.INSUFFICIENT_EVIDENCE
    await db_session.rollback()
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0


@pytest.mark.asyncio
async def test_unrequested_new_page_cannot_hide_among_retained_pages(db_session, test_settings):
    service, group, _, token, review, secret, view = await collection_context(db_session, test_settings)
    group.allow_files_from_device = True
    await db_session.commit()
    review = await read_history(service, token)
    secret, view = await start_draft(service, token, expected_review_version=review["review_version"], existing_secret=secret)
    view = await upload_draft_document(service, token, secret, side="cover", expected_revision=view.revision,
        idempotency_key=uuid.uuid4().hex, content=b"synthetic cover", content_type="image/jpeg", storage=MemoryStorage())
    with pytest.raises(ValidationError, match="not requested"):
        await complete_draft(service, token, secret, completion_body(review, view))
    await db_session.rollback()
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0


@pytest.mark.asyncio
async def test_qualifier_only_draft_attaches_selection_at_final_without_new_passport(db_session, test_settings):
    service, group, person, token, review, secret, view = await collection_context(db_session, test_settings, qualifier=True)
    choice = await qualifier_choice(service, group)
    view = await save_draft(service, token, secret, save_body(view, collection=FreshCollection(qualifier_selection_token=choice)))
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0
    result = await complete_draft(service, token, secret, completion_body(review, view))
    source = await db_session.get(PassportSubmissionModel, result[2])
    assert source.qualifier_enabled_snapshot and source.qualifier_is_self
    assert source.image_s3_key == person.asset.object_key and source.status == "submitted"
    assert person.profile.revision == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["missing", "expired", "foreign"])
async def test_invalid_qualifier_cannot_publish_any_source(db_session, test_settings, invalid):
    service, group, _, token, review, secret, view = await collection_context(db_session, test_settings, qualifier=True)
    choice = None
    if invalid == "expired":
        choice = await qualifier_choice(service, group)
        row = await db_session.scalar(select(QualifierSelectionModel))
        row.selected_at = row.created_at = datetime.now(UTC)-timedelta(days=2)
        row.expires_at = datetime.now(UTC)-timedelta(seconds=1)
        await db_session.commit()
    elif invalid == "foreign":
        choice = "a-different-unowned-selection-token"
    view = await save_draft(service, token, secret, save_body(view, collection=FreshCollection(qualifier_selection_token=choice)))
    with pytest.raises(ValidationError):
        await complete_draft(service, token, secret, completion_body(review, view))
    await db_session.rollback()
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0


@pytest.mark.asyncio
async def test_disabled_or_optional_photo_and_qualifier_are_not_required(db_session, test_settings):
    _, _, group, _, _, _ = await completion_context(db_session, test_settings)
    group.require_selfie = False
    group.upload_configuration = {"passport_upload_pages": ["front"], "visa_photo_required": True, "visa_photo_live_capture": True}
    assert missing_document_requirements(group, {"front"}) == []
    group.require_selfie = group.relation_with_qualifier_enabled = True
    group.upload_configuration = {"passport_upload_pages": ["front"], "visa_photo_required": False,
        "required_fields": {"relation_with_qualifier": False}}
    assert missing_document_requirements(group, {"front"}) == []
