"""Reuse submission is current, idempotent and cannot rewrite historical trips."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.application.travellers.completion import complete_reuse
from app.application.travellers.errors import ReuseError, ReuseReason
from app.application.travellers.history import read_history
from app.domain.exceptions.exceptions import ValidationError
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import TravellerParticipationModel
from tests.integration.test_returning_claims import successful_claim
from tests.integration.traveller_reuse_fixtures import reuse_context, seed_person


async def completion_context(session, settings):
    service, company, group = await reuse_context(session, settings)
    group.upload_configuration = {"passport_upload_pages": ["front"], "visa_photo_required": False}
    person = await seed_person(service, group)
    _, _, token = await successful_claim(service, group, person, "code")
    review = await read_history(service, token)
    assert review["missing_requirements"] == []
    return service, company, group, person, token, review


async def complete(service, token, review, **overrides):
    values = dict(requirements_version=review["question_version"], expected_review_version=review["review_version"],
        expected_participation_revision=review["participation_revision"], custom_answers={}, custom_detail_answers={},
        current_details={}, idempotency_key=uuid.uuid4().hex)
    values.update(overrides)
    return await complete_reuse(service, token, **values)


@pytest.mark.asyncio
async def test_success_creates_one_trip_snapshot_and_retry_is_idempotent(db_session, test_settings):
    service, _, group, person, token, review = await completion_context(db_session, test_settings)
    key = "synthetic-completion-idempotency"
    result = await complete(service, token, review, idempotency_key=key)
    assert result[1] == "submitted"
    assert await complete(service, token, review, idempotency_key=key) == result
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 1
    assert await db_session.scalar(select(func.count()).select_from(TravellerParticipationModel)) == 1
    source = await db_session.scalar(select(PassportSubmissionModel))
    participant = await db_session.get(TravellerParticipationModel, result[0])
    assert source.status == "client_submitted" and source.group_id == group.id
    assert source.image_s3_key == person.asset.object_key and source.extraction_status == "extraction_complete"
    assert participant.source_submission_id == source.id and participant.document_revision_id == person.document.id
    assert "MUST-NOT-LEAK" not in str(source.confirmed_fields) and "s3_key" not in source.confirmed_fields
    # Reusing the same idempotency key with different content is a conflict.
    with pytest.raises(ReuseError) as conflict:
        await complete(service, token, review, idempotency_key=key, current_details={"client_email": "different@example.com"})
    assert conflict.value.reason == ReuseReason.REVISION_CONFLICT


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["travel_date", "questions", "current_field", "passport_expiry", "asset_expiry"])
async def test_changed_review_or_unusable_asset_prevents_publication(db_session, test_settings, mutation):
    service, _, group, person, token, review = await completion_context(db_session, test_settings)
    if mutation == "travel_date":
        group.travel_date += timedelta(days=7)
    elif mutation == "questions":
        group.custom_questions = [{"id": str(uuid.uuid4()), "label": "Meal", "options": ["Veg", "Non Veg"], "enabled": True, "required": True}]
    elif mutation == "current_field":
        group.designation_enabled = True
    elif mutation == "passport_expiry":
        person.document.expiry_date = group.travel_date + timedelta(days=10)
    else:
        person.asset.retention_until = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    with pytest.raises(ReuseError):
        await complete(service, token, review)
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 0


@pytest.mark.asyncio
async def test_current_answers_required_and_stale_participation_revision_rejected(db_session, test_settings):
    service, _, group, _, token, _ = await completion_context(db_session, test_settings)
    question_id, detail_id = str(uuid.uuid4()), str(uuid.uuid4())
    group.custom_questions = [{"id": question_id, "label": "Meal", "options": ["Veg", "Jain"], "enabled": True, "required": True}]
    group.custom_details = [{"id": detail_id, "label": "Current office", "enabled": True, "required": True}]
    group.designation_enabled = True
    await db_session.commit()
    review = await read_history(service, token)
    with pytest.raises(ValidationError):
        await complete(service, token, review)
    result = await complete(service, token, review, custom_answers={question_id: "Jain"},
        custom_detail_answers={detail_id: "Current office"}, current_details={"designation": "Analyst"})
    source = await db_session.scalar(select(PassportSubmissionModel))
    assert source.custom_answers[0]["value"] == "Jain"
    assert source.confirmed_fields["designation"] == "Analyst"
    participant = await db_session.get(TravellerParticipationModel, result[0])
    assert participant.answers["custom_detail_answers"][0]["value"] == "Current office"
    with pytest.raises(ReuseError) as stale:
        await complete(service, token, review, custom_answers={question_id: "Jain"},
            custom_detail_answers={detail_id: "Other office"}, current_details={"designation": "Analyst"})
    assert stale.value.reason == ReuseReason.REVISION_CONFLICT


@pytest.mark.asyncio
async def test_independently_approved_snapshot_cannot_be_rewritten(db_session, test_settings):
    service, _, group, person, token, _ = await completion_context(db_session, test_settings)
    source = PassportSubmissionModel(agency_id=group.agency_id, group_id=group.id, client_name="Frozen name",
        client_phone="+919999999999", image_s3_key="old-independent-asset", status="staff_approved",
        confirmed_fields={"passport_number": person.number}, custom_answers=[])
    db_session.add(source)
    await db_session.flush()
    participant = TravellerParticipationModel(agency_id=group.agency_id, company_id=group.company_id,
        group_id=group.id, traveller_id=person.profile.id, passport_id=person.passport.id,
        document_revision_id=person.document.id, source_submission_id=source.id,
        source_kind="accepted_submission", profile_revision=1, contact_revision=1,
        question_version="frozen", status="accepted", idempotency_key=uuid.uuid4().hex)
    db_session.add(participant)
    await db_session.commit()
    review = await read_history(service, token)
    with pytest.raises(ReuseError) as conflict:
        await complete(service, token, review)
    assert conflict.value.reason == ReuseReason.REVISION_CONFLICT
    await db_session.refresh(source)
    assert source.status == "staff_approved" and source.client_name == "Frozen name"
    assert source.image_s3_key == "old-independent-asset"
