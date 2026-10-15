"""Drafts carry no official identity/contact mutation before final publication."""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.application.travellers.contact_change import send_contact_change_code
from app.application.travellers.draft_completion import complete_draft
from app.application.travellers.draft_contact import begin_draft_contact, verify_draft_contact
from app.application.travellers.draft_contracts import DraftComplete, DraftSave
from app.application.travellers.draft_uploads import upload_draft_document
from app.application.travellers.drafts import draft_view, require_draft, save_draft, start_draft
from app.application.travellers.errors import ReuseError
from app.application.travellers.grants import require_grant
from app.application.travellers.history import read_history
from app.application.travellers.operational_autoassignment import assign_operational_traveller
from app.domain.exceptions.exceptions import ValidationError
from app.infrastructure.database.models import (
    PassportPostSubmissionVerificationJobModel,
    PassportSubmissionModel,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerDraftAssetModel as Asset,
)
from app.infrastructure.database.traveller_returning_draft_models import (
    TravellerReturningDraftModel as Draft,
)
from app.infrastructure.database.traveller_reuse_models import (
    TravellerContactBindingModel,
    TravellerParticipationModel,
)
from tests.integration.test_returning_claims import successful_claim
from tests.integration.test_returning_completion import completion_context
from tests.integration.traveller_reuse_fixtures import FakeLimiter, FakeOTP, seed_person


class MemoryStorage:
    def __init__(self):
        self.files = {}

    async def upload_file(self, content, key, media):
        self.files[key] = content
        return key


async def draft_context(session, settings):
    values = await completion_context(session, settings)
    service, _, _, _, token, review = values
    secret, view = await start_draft(service, token, expected_review_version=review["review_version"])
    return (*values, secret, view)


def completion_body(review, view, **overrides):
    values = dict(expected_revision=view.revision, review_version=review["review_version"],
        question_version=review["question_version"], expected_participation_revision=review["participation_revision"],
        information_confirmed=True, idempotency_key=uuid.uuid4().hex)
    return DraftComplete(**{**values, **overrides})


def save_body(view, **overrides):
    values = {key: getattr(view, key) for key in ("passport_fields", "current_details", "custom_answers", "custom_detail_answers")}
    return DraftSave(**{**values, "expected_revision": view.revision, "idempotency_key": uuid.uuid4().hex, **overrides})


@pytest.mark.asyncio
async def test_save_resumes_without_mutating_official_records(db_session, test_settings):
    service, _, _, person, token, review, secret, view = await draft_context(db_session, test_settings)
    original = person.document.fields_ciphertext
    body = save_body(view, passport_fields={**view.passport_fields, "place_of_issue": "NEW PLACE"})
    saved = await save_draft(service, token, secret, body)
    assert saved.revision == view.revision + 1
    assert (await save_draft(service, token, secret, body)).revision == saved.revision
    same_secret, resumed = await start_draft(service, token, expected_review_version=review["review_version"], existing_secret=secret)
    assert same_secret == secret and resumed.passport_fields["place_of_issue"] == "NEW PLACE"
    assert person.document.fields_ciphertext == original and person.profile.revision == 1
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0
    row = await db_session.get(Draft, view.id)
    assert "NEW PLACE" not in row.payload_ciphertext
    with pytest.raises(ReuseError):
        await save_draft(service, token, secret, save_body(view))


@pytest.mark.asyncio
async def test_foreign_and_stale_authority_cannot_read_or_finalize(db_session, test_settings):
    service, _, group, person, token, review, secret, view = await draft_context(db_session, test_settings)
    other = await seed_person(service, group, 2)
    _, _, other_token = await successful_claim(service, group, other, "code")
    with pytest.raises(ReuseError):
        await require_draft(service, other_token, secret)
    person.profile.revision += 1
    await db_session.commit()
    with pytest.raises(ReuseError):
        await complete_draft(service, token, secret, completion_body(review, view))
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0


@pytest.mark.asyncio
async def test_final_unchanged_is_atomic_idempotent(db_session, test_settings):
    service, _, _, _, token, review, secret, view = await draft_context(db_session, test_settings)
    body = completion_body(review, view)
    result = await complete_draft(service, token, secret, body)
    assert result[1] == "submitted"
    assert await complete_draft(service, "", secret, body) == result
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 1
    assert await db_session.scalar(select(func.count()).select_from(TravellerParticipationModel)) == 1
    with pytest.raises(ReuseError):
        await complete_draft(service, "", secret, completion_body(review, view))


@pytest.mark.asyncio
async def test_otp_is_temporary_until_final_then_receipt_works_after_revocation(db_session, test_settings):
    service, _, _, person, token, review, secret, view = await draft_context(db_session, test_settings)
    claim = await begin_draft_contact(service, token, secret, phone_number="+919876540001")
    provider = FakeOTP()
    await send_contact_change_code(service, claim, provider=provider, ip_address="127.0.0.1", limiter=FakeLimiter())
    await verify_draft_contact(service, token, secret, claim, provider.code)
    assert person.profile.contact_revision == 1
    await require_grant(service, token, "history:read")
    view = await draft_view(service, await require_draft(service, token, secret))
    assert view.verified_phone == "+919876540001"
    body = completion_body(review, view)
    result = await complete_draft(service, token, secret, body)
    assert person.profile.contact_revision == 2
    current = await db_session.scalar(select(TravellerContactBindingModel).where(TravellerContactBindingModel.traveller_id == person.profile.id, TravellerContactBindingModel.status == "current"))
    assert service.crypto.decrypt(current.value_ciphertext) == "+919876540001"
    source = await db_session.get(PassportSubmissionModel, result[2])
    assert source.client_phone == "+919876540001"
    with pytest.raises(ReuseError):
        await require_grant(service, token, "history:read")
    assert await complete_draft(service, token, secret, body) == result
    assert person.profile.contact_revision == 2


@pytest.mark.asyncio
async def test_new_upload_replaces_only_temporary_asset_and_waits_for_extraction(db_session, test_settings):
    service, _, _, person, token, review, secret, view = await draft_context(db_session, test_settings)
    storage = MemoryStorage()
    for content in (b"first-image", b"second-image"):
        view = await upload_draft_document(service, token, secret, side="front", expected_revision=view.revision,
            idempotency_key=uuid.uuid4().hex, content=content, content_type="image/jpeg", storage=storage)
    rows = list(await db_session.scalars(select(Asset).order_by(Asset.created_at)))
    assert [row.state for row in rows] == ["discarded", "ready"]
    assert rows[1].is_current and view.passport_fields == {} and view.extraction_status == "pending"
    assert person.asset.object_key not in storage.files
    with pytest.raises(ValidationError):
        await complete_draft(service, token, secret, completion_body(review, view))
    await db_session.rollback()
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0


@pytest.mark.asyncio
async def test_corrected_fields_publish_review_candidate_not_canonical_history(db_session, test_settings):
    service, _, _, person, token, review, secret, view = await draft_context(db_session, test_settings)
    original = person.document.fields_ciphertext
    view = await save_draft(service, token, secret, save_body(view, passport_fields={**view.passport_fields, "place_of_issue": "CORRECTED"}))
    result = await complete_draft(service, token, secret, completion_body(review, view))
    source = await db_session.get(PassportSubmissionModel, result[2])
    assert source.status == "submitted" and source.confirmed_fields["place_of_issue"] == "CORRECTED"
    assert source.client_reviewed_at and source.post_submission_verification_revision == 1
    assert person.document.fields_ciphertext == original and person.profile.revision == 1
    assert await db_session.scalar(select(func.count()).select_from(PassportPostSubmissionVerificationJobModel)) == 1


@pytest.mark.asyncio
async def test_expired_draft_cannot_resume(db_session, test_settings):
    service, _, _, _, token, _, secret, view = await draft_context(db_session, test_settings)
    row = await db_session.get(Draft, view.id)
    row.created_at, row.expires_at = datetime.now(UTC) - timedelta(days=2), datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    with pytest.raises(ReuseError):
        await require_draft(service, token, secret)


@pytest.mark.asyncio
async def test_automatic_current_trip_is_updated_once_and_original_version_is_untouched(db_session, test_settings):
    service, _, group, person, token, _, _, _ = await draft_context(db_session, test_settings)
    assert await assign_operational_traveller(db_session, group=group, person_id=person.profile.id,
        source_kind="whatsapp_recipient", source_row_key=str(uuid.uuid4()), evidence={}, crypto=service.crypto, now=datetime.now(UTC)) == "assigned"
    await db_session.commit()
    source = await db_session.scalar(select(PassportSubmissionModel))
    source_id, original_fields = source.id, person.document.fields_ciphertext
    review = await read_history(service, token)
    secret, view = await start_draft(service, token, expected_review_version=review["review_version"])
    view = await save_draft(service, token, secret, save_body(view, passport_fields={**view.passport_fields, "place_of_issue": "REVIEWED PLACE"}))
    result = await complete_draft(service, token, secret, completion_body(review, view))
    assert result[2] == source_id and source.status == "submitted"
    assert source.confirmed_fields["place_of_issue"] == "REVIEWED PLACE"
    assert person.document.fields_ciphertext == original_fields
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 1


@pytest.mark.asyncio
async def test_requirements_refresh_keeps_unmodified_meaning_and_removes_obsolete_answers(db_session, test_settings):
    service, _, group, _, token, _, _, _ = await draft_context(db_session, test_settings)
    question = str(uuid.uuid4())
    group.custom_questions = [{"id": question, "label": "Meal", "options": ["Veg", "Jain"], "enabled": True, "required": False}]
    group.designation_enabled = True
    await db_session.commit()
    review = await read_history(service, token)
    secret, view = await start_draft(service, token, expected_review_version=review["review_version"])
    await save_draft(service, token, secret, save_body(view, custom_answers={question: "Jain"},
        current_details={"designation": "Engineer", "client_email": "person@example.com"}))
    group.custom_questions = [{"id": question, "label": "Completely changed meaning", "options": ["Veg", "Jain"], "enabled": True, "required": False}]
    group.designation_enabled = False
    await db_session.commit()
    current = await read_history(service, token)
    _, view = await start_draft(service, token, expected_review_version=current["review_version"], existing_secret=secret)
    assert view.custom_answers == {} and "designation" not in view.current_details
    assert view.current_details["client_email"] == "person@example.com"


@pytest.mark.asyncio
async def test_changed_draft_cannot_rewrite_past_trip_or_promote_staged_phone(db_session, test_settings):
    from tests.integration.test_operational_autoassignment import assign
    from tests.integration.test_returning_contact_change import pending_change, verify_change
    service, _, group, person, token, _, _, _ = await draft_context(db_session, test_settings)
    assert await assign(service, group, person) == "assigned"
    group.travel_date = datetime.now(UTC).date() - timedelta(days=2)
    await db_session.commit()
    source = await db_session.scalar(select(PassportSubmissionModel))
    original_fields, original_phone = dict(source.confirmed_fields), source.client_phone
    pending, provider = await pending_change(service, token)
    secret, _ = await verify_change(service, token, pending, provider.code)
    view = await draft_view(service, await require_draft(service, token, secret))
    view = await save_draft(service, token, secret, save_body(view, passport_fields={**view.passport_fields, "place_of_issue": "UPDATED PLACE"}))
    review = await read_history(service, token)
    with pytest.raises(ReuseError):
        await complete_draft(service, token, secret, completion_body(review, view))
    assert source.confirmed_fields == original_fields and source.client_phone == original_phone
    assert person.profile.contact_revision == 1
    assert await db_session.scalar(select(func.count()).select_from(PassportPostSubmissionVerificationJobModel)) == 0


@pytest.mark.asyncio
async def test_concurrent_final_receipt_recovers_after_waited_grant_is_revoked(db_session, test_settings, monkeypatch):
    from app.application.travellers import draft_completion
    from tests.integration.test_returning_contact_change import pending_change, verify_change
    service, _, _, person, token, _, _, _ = await draft_context(db_session, test_settings)
    pending, provider = await pending_change(service, token)
    secret, body = await verify_change(service, token, pending, provider.code)
    original_context = draft_completion.review_context
    competing = None

    async def finish_before_lock(*args):
        nonlocal competing
        monkeypatch.setattr(draft_completion, "review_context", original_context)
        competing = await complete_draft(service, token, secret, body)
        return await original_context(*args)

    monkeypatch.setattr(draft_completion, "review_context", finish_before_lock)
    assert await complete_draft(service, token, secret, body) == competing
    assert person.profile.contact_revision == 2
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 1


@pytest.mark.asyncio
async def test_explicit_draft_id_rejects_cookie_switch_between_people(db_session, test_settings):
    from starlette.requests import Request

    from app.presentation.api.v1.routes.returning_draft import draft_secret
    service, _, group, _, _, _, first_secret, first_view = await draft_context(db_session, test_settings)
    other = await seed_person(service, group, 2)
    _, _, other_token = await successful_claim(service, group, other, "code")
    review = await read_history(service, other_token)
    other_secret, other_view = await start_draft(service, other_token, expected_review_version=review["review_version"])
    request = Request({"type": "http", "method": "PUT", "path": "/api/v1/returning/draft",
        "headers": [(b"cookie", f"pd_returning_draft={other_secret}".encode())]})
    with pytest.raises(ReuseError):
        await draft_secret(request, expected_id=first_view.id, service=service)
    assert await draft_secret(request, expected_id=other_view.id, service=service) == other_secret
    assert first_secret != other_secret
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0
