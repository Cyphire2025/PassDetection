"""A public replacement association never substitutes for accepted evidence."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.application.travellers.enrollment import (
    EnrollmentError,
    EnrollmentRequest,
    enroll_submission,
)
from app.application.travellers.errors import ReuseError
from app.application.travellers.replacement import link_replacement_candidate
from app.infrastructure.database.models import PassportSubmissionModel, UserModel
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentRevisionModel,
    TravellerMatchCaseModel,
)
from tests.integration.test_returning_completion import completion_context


async def context(session, settings):
    service, company, group, person, token, review = await completion_context(session, settings)
    credential = uuid.uuid4().hex + uuid.uuid4().hex
    source = PassportSubmissionModel(agency_id=group.agency_id, group_id=group.id, client_name="New passport",
        image_s3_key="fresh/new-passport.jpg", status="client_submitted", extraction_revision=2,
        client_reviewed_at=datetime.now(UTC), upload_idempotency_key=credential,
        confirmed_fields={"passport_number": "00NEW12345", "issuing_country": "IND", "document_type": "P",
            "date_of_issue": "2026-01-01", "date_of_expiry": "2036-01-01", "date_of_birth": "1990-02-03"})
    session.add(source)
    await session.flush()
    arguments = dict(source_submission_id=source.id, upload_session_id=credential,
        expected_extraction_revision=2, expected_review_version=review["review_version"],
        change_kind="renewal", idempotency_key="synthetic-replacement")
    return service, company, group, person, token, source, arguments


@pytest.mark.asyncio
async def test_replacement_requires_upload_capability_and_is_provisional_and_idempotent(db_session, test_settings):
    service, _, _, person, token, source, args = await context(db_session, test_settings)
    with pytest.raises(ReuseError):
        async with db_session.begin_nested():
            await link_replacement_candidate(service, token, **{**args, "upload_session_id": "x" * 64})
    case_id = await link_replacement_candidate(service, token, **args)
    assert await link_replacement_candidate(service, token, **args) == case_id
    case = await db_session.get(TravellerMatchCaseModel, case_id)
    assert case.status == "provisional" and case.traveller_id == person.profile.id
    assert source.status == "client_submitted"
    assert await db_session.scalar(select(func.count()).select_from(TravellerDocumentRevisionModel)) == 1
    with pytest.raises(ReuseError):
        async with db_session.begin_nested():
            await link_replacement_candidate(service, token, **{**args, "change_kind": "correction"})


@pytest.mark.asyncio
async def test_staff_acceptance_can_resolve_unchanged_authorized_candidate(db_session, test_settings):
    service, company, group, person, token, source, args = await context(db_session, test_settings)
    await link_replacement_candidate(service, token, **args)
    actor = UserModel(agency_id=group.agency_id, email=f"{uuid.uuid4()}@example.invalid", full_name="Reviewer",
        hashed_password="unused", role="agency_admin")
    db_session.add(actor)
    source.status, source.extraction_revision = "staff_approved", 3
    await db_session.flush()
    request = EnrollmentRequest(group.agency_id, company.id, group.id, source.id, actor.id,
        group.company_revision, 3, "explicit-permission-reference", "enroll-public-replacement",
        candidate_association_confirmed=True)
    enrolled = await enroll_submission(db_session, request, service.crypto)
    assert enrolled.traveller_id == person.profile.id
    assert enrolled.passport_id != person.passport.id
    assert await enroll_submission(db_session, request, service.crypto) == enrolled


@pytest.mark.asyncio
async def test_edited_source_or_unacknowledged_candidate_cannot_silently_bind(db_session, test_settings):
    service, company, group, _, token, source, args = await context(db_session, test_settings)
    await link_replacement_candidate(service, token, **args)
    actor = UserModel(agency_id=group.agency_id, email=f"{uuid.uuid4()}@example.invalid", full_name="Reviewer",
        hashed_password="unused", role="agency_admin")
    db_session.add(actor)
    source.status, source.extraction_revision = "staff_approved", 3
    await db_session.flush()
    request = EnrollmentRequest(group.agency_id, company.id, group.id, source.id, actor.id,
        group.company_revision, 3, "explicit-permission-reference", "enroll-public-replacement")
    with pytest.raises(EnrollmentError, match="replacement_association_changed"):
        async with db_session.begin_nested():
            await enroll_submission(db_session, request, service.crypto)
    source.confirmed_fields = {**source.confirmed_fields, "passport_number": "CHANGED123"}
    await db_session.flush()
    with pytest.raises(EnrollmentError, match="replacement_association_changed"):
        async with db_session.begin_nested():
            await enroll_submission(db_session, replace(request, candidate_association_confirmed=True), service.crypto)
