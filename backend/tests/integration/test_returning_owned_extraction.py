"""Fresh/family hints remain non-authorizing and completion binds one member."""

import uuid

import pytest
from sqlalchemy import func, select

from app.application.travellers.errors import ReuseError
from app.application.travellers.identity_index import replace_identity_evidence
from app.domain.services.traveller_identity import identity_evidence
from app.infrastructure.database.models import PassportSubmissionModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerClaimModel,
    TravellerHistoryGrantModel,
)
from app.presentation.api.v1.routes.returning_detection import (
    DetectedHistoryRequest,
    detected_history,
)
from tests.integration.test_returning_completion import complete, completion_context
from tests.integration.traveller_reuse_fixtures import reuse_context, seed_person


async def owned_source(service, group, person):
    fields = {"passport_number": person.number, "date_of_birth": person.document.date_of_birth.isoformat()}
    name = service.crypto.decrypt(person.profile.display_name_ciphertext)
    await replace_identity_evidence(service.session, person=person.profile,
        evidence=identity_evidence(fields, name=name, phone=person.phone), crypto=service.crypto, source={"test": True})
    credential = uuid.uuid4().hex + uuid.uuid4().hex
    source = PassportSubmissionModel(agency_id=group.agency_id, group_id=group.id, client_name=name,
        client_phone=person.phone, image_s3_key="synthetic-owned-fresh.jpg", extracted_fields=fields,
        extraction_revision=4, extraction_status="extraction_complete", status="ready_for_client_review",
        upload_idempotency_key=credential)
    service.session.add(source)
    await service.session.flush()
    return source, credential


@pytest.mark.asyncio
async def test_detection_offers_only_boolean_and_creates_no_claim_or_grant(db_session, test_settings):
    service, _, group = await reuse_context(db_session, test_settings)
    person = await seed_person(service, group)
    source, credential = await owned_source(service, group, person)
    response = await detected_history(DetectedHistoryRequest(group_token=group.token,
        source_submission_id=source.id, expected_extraction_revision=4), credential, service)
    assert response.model_dump() == {"available": True}
    assert await db_session.scalar(select(func.count()).select_from(TravellerClaimModel)) == 0
    assert await db_session.scalar(select(func.count()).select_from(TravellerHistoryGrantModel)) == 0
    denied = await detected_history(DetectedHistoryRequest(group_token=group.token,
        source_submission_id=source.id, expected_extraction_revision=4), uuid.uuid4().hex, service)
    assert denied.model_dump() == {"available": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("ambiguous", [False, True])
async def test_partial_name_detection_remains_only_a_hint_and_ambiguity_hides_it(db_session, test_settings, ambiguous):
    service, _, group = await reuse_context(db_session, test_settings)
    person = await seed_person(service, group)
    source, credential = await owned_source(service, group, person)
    saved_name = service.crypto.decrypt(person.profile.display_name_ciphertext)
    source.client_name = saved_name + " Extra"
    if ambiguous:
        another = await seed_person(service, group, 2)
        await replace_identity_evidence(service.session, person=another.profile,
            evidence=identity_evidence(source.extracted_fields, name="Different Holder", phone=person.phone),
            crypto=service.crypto, source={"test": True})
    await db_session.flush()
    response = await detected_history(DetectedHistoryRequest(group_token=group.token,
        source_submission_id=source.id, expected_extraction_revision=4), credential, service)
    assert response.model_dump() == {"available": not ambiguous}
    assert await db_session.scalar(select(func.count()).select_from(TravellerClaimModel)) == 0
    assert await db_session.scalar(select(func.count()).select_from(TravellerHistoryGrantModel)) == 0


@pytest.mark.asyncio
async def test_owned_member_completion_returns_real_snapshot_and_retries_without_touching_drafts(db_session, test_settings):
    service, _, group, person, token, review = await completion_context(db_session, test_settings)
    source, credential = await owned_source(service, group, person)
    another = await seed_person(service, group, 2)
    other_source, _ = await owned_source(service, group, another)
    await db_session.commit()
    values = {"owned_source_id": source.id, "owned_source_revision": 4,
              "upload_session_id": credential, "idempotency_key": "one-family-member"}
    result = await complete(service, token, review, **values)
    assert await complete(service, token, review, **values) == result
    assert result[2] != source.id and result[2] != other_source.id
    actual = await db_session.get(PassportSubmissionModel, result[2])
    assert actual.status == "client_submitted" and actual.client_reviewed_at is not None
    await db_session.refresh(source)
    await db_session.refresh(other_source)
    assert source.status == other_source.status == "ready_for_client_review"
    assert source.client_reviewed_at is other_source.client_reviewed_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["different_member", "stale_revision", "wrong_credential", "other_group"])
async def test_verified_grant_cannot_complete_a_different_or_stale_family_source(db_session, test_settings, failure):
    service, _, group, person, token, review = await completion_context(db_session, test_settings)
    if failure == "different_member":
        person = await seed_person(service, group, 2)
    source, credential = await owned_source(service, group, person)
    if failure == "other_group":
        _, _, foreign_group = await reuse_context(db_session, test_settings)
        source.group_id, source.agency_id = foreign_group.id, foreign_group.agency_id
    await db_session.commit()
    with pytest.raises(ReuseError):
        await complete(service, token, review, owned_source_id=source.id,
            owned_source_revision=3 if failure == "stale_revision" else 4,
            upload_session_id=uuid.uuid4().hex if failure == "wrong_credential" else credential)
    assert await db_session.scalar(select(func.count()).select_from(PassportSubmissionModel)) == 1
