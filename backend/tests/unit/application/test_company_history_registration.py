"""Bounded historical registration keeps provenance without inventing consent."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.application.travellers.enrollment import enroll_submission
from app.application.travellers.historical_registration import register_historical_source
from app.application.travellers.identity_index import (
    COMPANY_INDIVIDUAL_CODE,
    find_exact_identity,
    replace_identity_evidence,
    replace_phone_identity_evidence,
)
from app.application.travellers.retained_authority import has_retained_authority
from app.domain.services.traveller_identity import identity_evidence
from app.infrastructure.database.traveller_reuse_models import (
    TravellerDocumentRevisionModel,
    TravellerIdentifierModel,
    TravellerMatchCaseModel,
    TravellerProfileModel,
    TravellerReusePolicyModel,
)
from tests.unit.application.test_traveller_enrollment import _fixture, _source


async def register(session, ctx, source=None):
    policy = await session.get(TravellerReusePolicyModel, ctx.group.company_id)
    policy.configured_by_user_id = ctx.request.actor_id
    return await register_historical_source(session, group=ctx.group, source_id=(source or ctx.source).id,
        policy=policy, crypto=ctx.crypto, now=datetime.now(UTC))


@pytest.mark.asyncio
async def test_registration_is_idempotent_and_retains_each_duplicate_source_link(db_session):
    ctx = await _fixture(db_session)
    person_id = await register(db_session, ctx)
    assert await register(db_session, ctx) == person_id
    second = _source(ctx.group)
    db_session.add(second)
    await db_session.flush()
    assert await register(db_session, ctx, second) == person_id
    assert await db_session.scalar(select(func.count()).select_from(TravellerProfileModel)) == 1
    assert await db_session.scalar(select(func.count()).select_from(TravellerMatchCaseModel)) == 2
    assert await db_session.scalar(select(func.count()).select_from(TravellerDocumentRevisionModel)) == 2
    person = await db_session.get(TravellerProfileModel, person_id)
    assert person.reuse_permission_status == "unknown" and has_retained_authority(person)
    assert "consent" not in person.reuse_permission_evidence


@pytest.mark.asyncio
async def test_missing_context_keeps_private_source_without_reusable_document(db_session):
    ctx = await _fixture(db_session)
    ctx.source.confirmed_fields = {"passport_number": "001234567", "date_of_birth": "1990-01-01"}
    await db_session.flush()
    person_id = await register(db_session, ctx)
    assert person_id is not None
    assert await db_session.scalar(select(func.count()).select_from(TravellerDocumentRevisionModel)) == 0
    case = await db_session.scalar(select(TravellerMatchCaseModel))
    assert case.traveller_id == person_id and case.source_row_key == str(ctx.source.id)
    assert case.evidence["document_registration_reason"] == "reliable_issuing_context_required"


@pytest.mark.asyncio
async def test_conflicting_passport_creates_separate_review_identity_without_merge(db_session):
    ctx = await _fixture(db_session)
    first = await register(db_session, ctx)
    second = _source(ctx.group, number="009999999")
    db_session.add(second)
    await db_session.flush()
    second_id = await register(db_session, ctx, second)
    assert first != second_id
    profile = await db_session.get(TravellerProfileModel, second_id)
    assert profile.status == "review_required" and not has_retained_authority(profile)
    case = await db_session.scalar(select(TravellerMatchCaseModel).where(TravellerMatchCaseModel.traveller_id == second_id))
    assert case.evidence["possible_duplicate"] is True


@pytest.mark.asyncio
async def test_index_scope_and_ambiguity_never_select_a_person(db_session):
    ctx, other = await _fixture(db_session), await _fixture(db_session)
    person = await register(db_session, ctx)
    evidence = identity_evidence(ctx.source.confirmed_fields, name=ctx.source.client_name, phone=ctx.source.client_phone)
    found = await find_exact_identity(db_session, agency_id=ctx.group.agency_id, company_id=ctx.group.company_id,
        evidence=evidence, crypto=ctx.crypto)
    assert found.traveller_id == person
    foreign = await find_exact_identity(db_session, agency_id=other.group.agency_id, company_id=other.group.company_id,
        evidence=evidence, crypto=ctx.crypto)
    assert foreign.traveller_id is None


@pytest.mark.asyncio
async def test_canonical_individual_code_and_verified_phone_update_preserve_other_signals(db_session):
    ctx = await _fixture(db_session)
    person_id = await register(db_session, ctx)
    person = await db_session.get(TravellerProfileModel, person_id)
    fields = {**ctx.source.confirmed_fields, "agent_code": "Ａ１２３", "staff_code": "A123"}
    await replace_identity_evidence(db_session, person=person,
        evidence=identity_evidence(fields, name=ctx.source.client_name, phone="919999999999"),
        crypto=ctx.crypto, source={"kind": "synthetic_test"})
    before = list((await db_session.scalars(select(TravellerIdentifierModel).where(
        TravellerIdentifierModel.traveller_id == person_id))).all())
    code_rows = [row for row in before if row.identifier_type == COMPANY_INDIVIDUAL_CODE]
    assert len(code_rows) == 1 and ctx.crypto.decrypt(code_rows[0].value_ciphertext) == "A123"
    assert code_rows[0].is_individual is True
    assert code_rows[0].value_fingerprint == ctx.crypto.scoped_digest("identifier",
        person.agency_id, person.company_id, COMPANY_INDIVIDUAL_CODE, "A123")
    stable_ids = {row.id for row in before if row.identifier_type != "identity_v1:phone"}
    await replace_phone_identity_evidence(db_session, person=person, normalized_phone="918888888888",
        crypto=ctx.crypto, source={"kind": "verified_contact_change"})
    await db_session.flush()
    after = list((await db_session.scalars(select(TravellerIdentifierModel).where(
        TravellerIdentifierModel.traveller_id == person_id))).all())
    assert stable_ids == {row.id for row in after if row.identifier_type != "identity_v1:phone"}
    phone_rows = [row for row in after if row.identifier_type == "identity_v1:phone"]
    assert len(phone_rows) == 1 and ctx.crypto.decrypt(phone_rows[0].value_ciphertext) == "918888888888"


@pytest.mark.asyncio
async def test_generated_trip_snapshot_is_linked_without_reenrollment_or_revision_churn(db_session, test_settings):
    from app.infrastructure.database.models import PassportSubmissionModel
    from tests.integration.test_operational_autoassignment import assign
    from tests.integration.traveller_reuse_fixtures import reuse_context, seed_person

    service, _, group = await reuse_context(db_session, test_settings)
    person = await seed_person(service, group)
    assert await assign(service, group, person) == "assigned"
    source = await db_session.scalar(select(PassportSubmissionModel))
    profile_revision = person.profile.revision
    for _ in range(2):
        result = await register_historical_source(db_session, group=group, source_id=source.id,
            policy=None, crypto=service.crypto, now=datetime.now(UTC))
        assert result == person.profile.id
        await db_session.flush()
    assert await db_session.scalar(select(func.count()).select_from(TravellerProfileModel)) == 1
    assert await db_session.scalar(select(func.count()).select_from(TravellerDocumentRevisionModel)) == 1
    assert person.profile.revision == profile_revision
    case = await db_session.scalar(select(TravellerMatchCaseModel))
    assert case.reason_code == "retained_trip_snapshot" and case.source_created_at == source.created_at
    # Copied metadata without the actual same-source participation is not proof.
    spoof = _source(group)
    spoof.staff_metadata = dict(source.staff_metadata)
    db_session.add(spoof)
    await db_session.flush()
    assert await register_historical_source(db_session, group=group, source_id=spoof.id,
        policy=None, crypto=service.crypto, now=datetime.now(UTC)) is None
    assert await db_session.scalar(select(func.count()).select_from(TravellerMatchCaseModel)) == 1


@pytest.mark.asyncio
async def test_later_staff_acceptance_promotes_same_historical_person_without_duplicate(db_session):
    ctx = await _fixture(db_session)
    ctx.source.status = "client_submitted"
    await db_session.flush()
    person_id = await register(db_session, ctx)
    assert await db_session.scalar(select(func.count()).select_from(TravellerDocumentRevisionModel)) == 0
    ctx.source.status = "staff_approved"
    ctx.source.extraction_revision += 1
    await db_session.flush()
    assert await register(db_session, ctx) == person_id
    assert await db_session.scalar(select(func.count()).select_from(TravellerProfileModel)) == 1
    assert await db_session.scalar(select(func.count()).select_from(TravellerDocumentRevisionModel)) == 1
    assert await register(db_session, ctx) == person_id
    assert await db_session.scalar(select(func.count()).select_from(TravellerDocumentRevisionModel)) == 1


@pytest.mark.asyncio
async def test_edited_source_cannot_reassign_original_identity_or_replace_accepted_fields(db_session):
    ctx = await _fixture(db_session)
    ctx.source.status = "client_submitted"
    person_id = await register(db_session, ctx)
    ctx.source.status, ctx.source.extraction_revision = "staff_approved", 2
    ctx.source.confirmed_fields = {**ctx.source.confirmed_fields, "passport_number": "OTHER123"}
    await db_session.flush()
    assert await register(db_session, ctx) == person_id
    assert await db_session.scalar(select(func.count()).select_from(TravellerDocumentRevisionModel)) == 0
    case = await db_session.scalar(select(TravellerMatchCaseModel))
    assert case.evidence["document_registration_reason"] == "source_identity_changed"


@pytest.mark.asyncio
async def test_existing_staff_enrollment_gets_current_identity_index_without_new_document(db_session):
    ctx = await _fixture(db_session)
    enrollment = await enroll_submission(db_session, ctx.request, ctx.crypto)
    db_session.add(TravellerMatchCaseModel(agency_id=ctx.group.agency_id, company_id=ctx.group.company_id,
        group_id=ctx.group.id, source_kind="passport_submission", source_row_key=str(ctx.source.id),
        status="resolved", reason_code="explicit_staff_enrollment", traveller_id=enrollment.traveller_id))
    await db_session.flush()
    assert await register(db_session, ctx) == enrollment.traveller_id
    assert await db_session.scalar(select(func.count()).select_from(TravellerDocumentRevisionModel)) == 1
    assert await db_session.scalar(select(func.count()).select_from(TravellerIdentifierModel).where(
        TravellerIdentifierModel.identifier_type == "identity_v1:name")) == 1


@pytest.mark.asyncio
async def test_private_registration_is_independent_of_reuse_and_enable_upgrades_same_person(db_session):
    ctx = await _fixture(db_session)
    person_id = await register_historical_source(db_session, group=ctx.group, source_id=ctx.source.id,
        policy=None, crypto=ctx.crypto, now=datetime.now(UTC))
    person = await db_session.get(TravellerProfileModel, person_id)
    assert person.reuse_permission_status == "unknown" and not has_retained_authority(person)
    assert person.reuse_permission_evidence == {"authority_kind": "private_history_v1",
                                               "source_submission_id": str(ctx.source.id)}
    assert await db_session.scalar(select(func.count()).select_from(TravellerDocumentRevisionModel)) == 0
    assert await register(db_session, ctx) == person_id
    assert has_retained_authority(person) and person.reuse_permission_status == "unknown"
    assert await db_session.scalar(select(func.count()).select_from(TravellerDocumentRevisionModel)) == 1
